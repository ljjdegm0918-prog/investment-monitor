"""EDGAR fallback for explicitly reviewed Singapore cross-listings.

There is no ticker discovery here.  A local mapping file is required so an
SEC issuer cannot be silently attached to a similarly named SGX company.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timezone
import json
import os
from pathlib import Path
from typing import Any, Iterable, List, Mapping, Optional, Protocol, Sequence, Tuple

from ...connectors.base import ConnectorUnavailableError
from ...models import CollectionRequest, InformationItem, MARKET_SG
from ...provenance import build_raw_provenance
from ...web_repository import normalize_sg_ticker
from ..sec.client import SECClient
from ..sec.connector import ARCHIVES_BASE_URL, SUBMISSIONS_BASE_URL, _filing_url, _historical_file_overlaps, _submission_url


ALLOWED_FORMS = frozenset({"6-K", "6-K/A", "20-F", "20-F/A", "F-1", "F-1/A", "F-3", "F-3/A", "8-K", "8-K/A"})
IDENTITY_SCHEMA = "sg_edgar_identity/v1"
IDENTITY_PATH_ENV = "SG_EDGAR_IDENTITY_PATH"


class JSONClient(Protocol):
    def get_json(self, url: str) -> Any: ...


class SgEdgarDataError(RuntimeError):
    pass


@dataclass(frozen=True)
class SgEdgarIdentity:
    sg_ticker: str
    exchange: str
    us_ticker: str
    cik: int
    issuer: str = ""
    mapping_source: str = "manual_review"
    mapping_version: str = "1"

    def __post_init__(self) -> None:
        ticker = normalize_sg_ticker(self.sg_ticker)
        exchange = str(self.exchange).strip()
        us_ticker = str(self.us_ticker).strip().upper()
        if not ticker or not exchange or not us_ticker or int(self.cik) <= 0:
            raise ValueError("SgEdgarIdentity requires sg_ticker, exchange, us_ticker and positive cik")
        object.__setattr__(self, "sg_ticker", ticker)
        object.__setattr__(self, "exchange", exchange)
        object.__setattr__(self, "us_ticker", us_ticker)
        object.__setattr__(self, "cik", int(self.cik))
        object.__setattr__(self, "issuer", str(self.issuer).strip())
        object.__setattr__(self, "mapping_source", str(self.mapping_source).strip() or "manual_review")
        object.__setattr__(self, "mapping_version", str(self.mapping_version).strip() or "1")


@dataclass(frozen=True)
class SgEdgarCollectionFailure:
    ticker: str
    message: str


class SgEdgarConnector:
    """Collect permitted SEC forms without claiming SGXNET coverage."""

    name = "sg_edgar"
    provider = "US SEC EDGAR (Singapore cross-listing fallback; not SGXNET)"
    coverage_level = "tier_1_us_regulatory_non_sgx"
    coverage_kind = "complete_window"
    source_type = "regulatory_filing"

    def __init__(self, *, client: JSONClient, identities: Iterable[SgEdgarIdentity] = ()) -> None:
        self._client = client
        self._identities = tuple(identities)
        self._last_errors: Tuple[SgEdgarCollectionFailure, ...] = ()
        self.last_collection_status = "empty"
        self.last_records_read = 0

    @classmethod
    def configuration_error(cls) -> Optional[str]:
        missing = []
        if not os.environ.get("SEC_USER_AGENT", "").strip():
            missing.append("SEC_USER_AGENT")
        raw_path = os.environ.get(IDENTITY_PATH_ENV, "").strip()
        if not raw_path:
            missing.append(IDENTITY_PATH_ENV)
        if missing:
            return f"{', '.join(missing)} is not configured; SG EDGAR requires an identified SEC client and reviewed identity mappings."
        path = Path(raw_path)
        if not path.is_file():
            return f"{IDENTITY_PATH_ENV} is not a readable mapping file: {path}"
        try:
            load_identities_from_path(path)
        except (OSError, ValueError, json.JSONDecodeError, SgEdgarDataError) as error:
            return f"SG EDGAR identity mapping is invalid: {error}"
        return None

    @classmethod
    def from_environment(cls) -> "SgEdgarConnector":
        configuration_error = cls.configuration_error()
        if configuration_error:
            raise ConnectorUnavailableError(configuration_error)
        try:
            return cls(client=SECClient.from_environment(), identities=load_identities_from_path(Path(os.environ[IDENTITY_PATH_ENV])))
        except Exception as caught:
            raise ConnectorUnavailableError(f"SG EDGAR is not connected: {caught}") from caught

    @property
    def last_errors(self) -> Tuple[SgEdgarCollectionFailure, ...]:
        return self._last_errors

    def collect(self, request: CollectionRequest) -> List[InformationItem]:
        requested = tuple(dict.fromkeys(normalize_sg_ticker(t) for t in request.tickers if self._is_sg_request(request, t)))
        if not requested:
            self._last_errors, self.last_collection_status, self.last_records_read = (), "empty", 0
            return []
        items: List[InformationItem] = []
        failures: List[SgEdgarCollectionFailure] = []
        records_read = successes = 0
        collected_at = datetime.now(timezone.utc)
        for ticker in requested:
            try:
                identity = self._resolve_identity(ticker)
                result, count = self._collect_identity(identity, request.start_date, request.end_date, collected_at)
                items.extend(result); records_read += count; successes += 1
            except Exception as error:
                failures.append(SgEdgarCollectionFailure(ticker, str(error) or error.__class__.__name__))
        self._last_errors, self.last_records_read = tuple(failures), records_read
        self.last_collection_status = "partial" if failures and successes else "unavailable" if failures else "success" if items else "empty"
        return items

    @staticmethod
    def _is_sg_request(request: CollectionRequest, ticker: str) -> bool:
        return bool(
            request.market_for(ticker) == MARKET_SG
            or request.market_for(normalize_sg_ticker(ticker)) == MARKET_SG
        )

    def _resolve_identity(self, ticker: str) -> SgEdgarIdentity:
        matches = tuple(item for item in self._identities if item.sg_ticker == ticker)
        if not matches:
            raise SgEdgarDataError(f"No explicit SG ticker to EDGAR mapping for {ticker}")
        if len(matches) != 1:
            raise SgEdgarDataError(f"Conflicting SG EDGAR mappings for {ticker}: {', '.join(sorted(item.exchange for item in matches))}")
        return matches[0]

    def _collect_identity(self, identity: SgEdgarIdentity, start: date, end: date, collected_at: datetime) -> Tuple[List[InformationItem], int]:
        submission_url = _submission_url(identity.cik)
        payload = self._client.get_json(submission_url)
        _verify_identity(payload, identity)
        issuer = _company_name(payload) or identity.issuer
        if not issuer:
            raise SgEdgarDataError(f"SEC submissions response has no issuer name for CIK {identity.cik:010d}")
        items: List[InformationItem] = []; count = 0
        for table in self._tables(payload, start, end):
            mapped, read = self._map_table(table, identity, issuer, start, end, collected_at, submission_url)
            items.extend(mapped); count += read
        return items, count

    def _tables(self, payload: Any, start: date, end: date) -> Iterable[Mapping[str, Any]]:
        try:
            filings = payload["filings"]; recent = filings["recent"]; files = filings.get("files", [])
        except (KeyError, TypeError) as error:
            raise SgEdgarDataError("SEC submissions response has an unexpected structure") from error
        if not isinstance(recent, Mapping) or not isinstance(files, list):
            raise SgEdgarDataError("SEC submissions filing tables have an unexpected structure")
        yield recent
        for row in files:
            if not isinstance(row, Mapping) or not _historical_file_overlaps(row, start, end):
                continue
            name = row.get("name")
            if not isinstance(name, str) or not name.strip():
                raise SgEdgarDataError("SEC historical submissions entry has no name")
            historical = self._client.get_json(f"{SUBMISSIONS_BASE_URL}/{name}")
            if not isinstance(historical, Mapping):
                raise SgEdgarDataError(f"SEC historical submissions file is invalid: {name}")
            yield historical

    def _map_table(self, table: Mapping[str, Any], identity: SgEdgarIdentity, issuer: str, start: date, end: date, collected_at: datetime, submission_url: str) -> Tuple[List[InformationItem], int]:
        columns = _columns(table); count = len(columns["accessionNumber"]); items = []
        for i in range(count):
            filing_date = _date(columns["filingDate"][i])
            if not start <= filing_date <= end: continue
            form = str(columns["form"][i] or "").strip().upper()
            if form not in ALLOWED_FORMS: continue
            accession = str(columns["accessionNumber"][i] or "").strip()
            if not accession: raise SgEdgarDataError("SEC filing row has no accession number")
            primary = str(columns["primaryDocument"][i] or "").strip(); desc = str(columns["primaryDocDescription"][i] or "").strip()
            document_url = _filing_url(identity.cik, accession, primary)
            directory = _directory_url(identity.cik, accession); index_url = f"{directory}/index.json"; accession_url = f"{directory}/{accession}-index.html"
            index_payload = self._client.get_json(index_url); attachments = _attachments(index_payload, directory, document_url)
            acceptance = _effective_datetime(table.get("acceptanceDateTime"), i)
            filing_type = _filing_type(form, desc)
            raw = {"submissions_row": _raw_row(table, i), "attachment_index": index_payload, "identity": {"sg_ticker": identity.sg_ticker, "exchange": identity.exchange, "us_ticker": identity.us_ticker, "cik": f"{identity.cik:010d}", "mapping_source": identity.mapping_source, "mapping_version": identity.mapping_version}}
            metadata = {**build_raw_provenance(official_source_id=accession, official_source_url=accession_url, retrieval_url=index_url, raw_payload=raw, raw_payload_format="json", classification_code=form, classification_label=desc or form, published_at_raw=filing_date.isoformat(), published_timezone="UTC", revision_semantics="amendment" if form.endswith("/A") else "original"), "source_tier": 1, "source_tier_label": "us_regulator", "source_name": "sec", "source_role": "us_regulatory_fallback", "is_official": True, "officiality": "US_regulatory_filing", "is_sgx_announcement": False, "non_sgx": True, "cross_verified": False, "attachments_may_be_missing": False, "regulatory_jurisdiction": "US", "coverage_level": self.coverage_level, "cik": f"{identity.cik:010d}", "sg_ticker": identity.sg_ticker, "exchange": identity.exchange, "us_ticker": identity.us_ticker, "mapping_source": identity.mapping_source, "mapping_version": identity.mapping_version, "accession_number": accession, "accession_url": accession_url, "document_url": document_url, "index_url": index_url, "attachments": attachments, "attachment_urls": attachments, "filing_type": filing_type, "sec_form": form, "collection_status": "success", "submission_url": submission_url}
            items.append(InformationItem(source=self.name, source_type="regulatory_filing", external_id=f"sec:{identity.cik:010d}:{accession}", tickers=(identity.sg_ticker,), issuer=issuer, published_at=datetime.combine(filing_date, datetime.min.time(), tzinfo=timezone.utc), title=desc or f"SEC Form {form} filing for Singapore cross-listed issuer", document_type=filing_type, url=document_url, collected_at=collected_at, raw_metadata=metadata, market=MARKET_SG, effective_at=acceptance))
        return items, count


def load_identities_from_path(path: Path) -> Tuple[SgEdgarIdentity, ...]:
    try: payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error: raise SgEdgarDataError(f"Could not read SG EDGAR identity mapping: {path}") from error
    if not isinstance(payload, Mapping) or set(payload) != {"schema", "identities"} or payload.get("schema") != IDENTITY_SCHEMA:
        raise SgEdgarDataError(f"SG EDGAR identity mapping must contain exactly schema and identities with schema {IDENTITY_SCHEMA!r}")
    rows = payload.get("identities")
    if not isinstance(rows, list) or not rows: raise SgEdgarDataError("SG EDGAR identity mapping must contain identities")
    result = []
    required, optional = {"sg_ticker", "exchange", "us_ticker", "cik"}, {"issuer", "mapping_source", "mapping_version"}
    for i, row in enumerate(rows):
        if not isinstance(row, Mapping) or not required.issubset(row) or set(row) - required - optional: raise SgEdgarDataError(f"SG EDGAR identity at index {i} has an invalid field set")
        try:
            result.append(SgEdgarIdentity(str(row["sg_ticker"]), str(row["exchange"]), str(row["us_ticker"]), _cik(row["cik"], i), str(row.get("issuer") or ""), str(row.get("mapping_source") or "manual_review"), str(row.get("mapping_version") or "1")))
        except (TypeError, ValueError) as error: raise SgEdgarDataError(f"SG EDGAR identity at index {i} is invalid: {error}") from error
    return tuple(result)


def _cik(value: Any, index: int) -> int:
    if isinstance(value, bool): raise SgEdgarDataError(f"SG EDGAR identity at index {index} has no valid cik")
    try: return int(value)
    except (TypeError, ValueError) as error: raise SgEdgarDataError(f"SG EDGAR identity at index {index} has no valid cik") from error


def _columns(table: Mapping[str, Any]) -> Mapping[str, Sequence[Any]]:
    required = ("accessionNumber", "filingDate", "form", "primaryDocument", "primaryDocDescription")
    try: columns = {name: table[name] for name in required}
    except KeyError as error: raise SgEdgarDataError(f"SEC filing table is missing column: {error.args[0]}") from error
    if any(not isinstance(v, list) for v in columns.values()) or any(len(v) != len(columns["accessionNumber"]) for v in columns.values()): raise SgEdgarDataError("SEC filing table columns are invalid")
    return columns


def _date(value: Any) -> date:
    try: return date.fromisoformat(str(value))
    except ValueError as error: raise SgEdgarDataError("SEC filingDate is not a valid ISO date") from error


def _directory_url(cik: int, accession: str) -> str:
    digits = accession.replace("-", "")
    if not digits.isdigit(): raise SgEdgarDataError(f"SEC accession number is invalid: {accession!r}")
    return f"{ARCHIVES_BASE_URL}/{cik}/{digits}"


def _attachments(payload: Any, directory: str, document_url: str) -> List[str]:
    entries = payload.get("directory", {}).get("item") if isinstance(payload, Mapping) and isinstance(payload.get("directory"), Mapping) else None
    if not isinstance(entries, list): raise SgEdgarDataError("SEC filing index has no directory item list")
    urls = []
    for entry in entries:
        name = entry.get("name") if isinstance(entry, Mapping) else None
        if not isinstance(name, str) or not name.strip() or "/" in name or "\\" in name: raise SgEdgarDataError("SEC filing index has an unsafe document name")
        url = f"{directory}/{name}"
        if url not in urls: urls.append(url)
    if not urls: raise SgEdgarDataError("SEC filing index has no attachments")
    return [document_url] + [url for url in urls if url != document_url]


def _verify_identity(payload: Any, identity: SgEdgarIdentity) -> None:
    tickers = payload.get("tickers") if isinstance(payload, Mapping) else None
    values = {v.strip().upper() for v in tickers if isinstance(v, str) and v.strip()} if isinstance(tickers, list) else set()
    if identity.us_ticker not in values: raise SgEdgarDataError(f"Explicit SG EDGAR mapping disagrees with SEC submissions ticker for {identity.sg_ticker}: expected {identity.us_ticker}")


def _company_name(payload: Any) -> str:
    value = payload.get("name") if isinstance(payload, Mapping) else None
    return value.strip() if isinstance(value, str) else ""


def _raw_row(table: Mapping[str, Any], index: int) -> Mapping[str, Any]:
    return {str(k): v[index] for k, v in table.items() if isinstance(v, list) and index < len(v)}


def _filing_type(form: str, description: str) -> str:
    if form.startswith("20-F"): return "annual_report"
    if form.startswith(("F-1", "F-3")): return "prospectus"
    text = description.casefold()
    if any(term in text for term in ("earnings", "financial results")): return "financial_results"
    if any(term in text for term in ("acquisition", "merger", "disposition")): return "acquisition_disposal"
    if any(term in text for term in ("financing", "offering", "debt")): return "financing"
    return "material_information"


def _effective_datetime(values: Any, index: int) -> Optional[datetime]:
    if not isinstance(values, list) or index >= len(values) or values[index] is None: return None
    try: parsed = datetime.fromisoformat(str(values[index]).replace("Z", "+00:00"))
    except ValueError: return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
