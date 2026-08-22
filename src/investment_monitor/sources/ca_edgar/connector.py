"""Canadian-listing EDGAR fallback with explicit, reviewable identity maps.

EDGAR is a US regulatory source, not a SEDAR+ replacement.  The connector is
therefore only usable for Canadian listings whose CA ticker/exchange has been
explicitly mapped to an SEC CIK and US ticker by the caller.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timezone
import json
import os
from pathlib import Path
from typing import Any, Iterable, List, Mapping, Optional, Protocol, Sequence, Tuple

from ...connectors.base import ConnectorUnavailableError
from ...models import CollectionRequest, InformationItem, MARKET_CA
from ...provenance import build_raw_provenance
from ...web_repository import infer_ca_board, normalize_ca_ticker
from ..sec.connector import (
    ARCHIVES_BASE_URL,
    SUBMISSIONS_BASE_URL,
    _filing_url,
    _historical_file_overlaps,
    _submission_url,
)
from ..sec.client import SECClient


ALLOWED_FORMS = frozenset({
    "6-K", "40-F", "40-F/A", "20-F", "20-F/A", "F-10", "F-10/A",
    "8-K", "8-K/A",
})
IDENTITY_SCHEMA = "ca_edgar_identity/v1"
IDENTITY_PATH_ENV = "CA_EDGAR_IDENTITY_PATH"


class JSONClient(Protocol):
    """The SEC JSON surface required by the CA-specific fallback."""

    def get_json(self, url: str) -> Any:
        ...


class CaEdgarDataError(RuntimeError):
    """A mapped Canadian EDGAR response was incomplete or malformed."""


@dataclass(frozen=True)
class CaEdgarIdentity:
    """One reviewed CA listing to SEC identity relation.

    ``ca_ticker`` intentionally excludes the exchange suffix.  ``exchange``
    remains mandatory because a Canadian root symbol alone is not a universal
    identity; it is also preserved with every collected disclosure.
    """

    ca_ticker: str
    exchange: str
    us_ticker: str
    cik: int
    issuer: str = ""
    mapping_source: str = "manual_review"
    mapping_version: str = "1"

    def __post_init__(self) -> None:
        ticker = normalize_ca_ticker(self.ca_ticker)
        if not ticker:
            raise ValueError("CaEdgarIdentity.ca_ticker must be non-empty")
        if not str(self.exchange).strip():
            raise ValueError("CaEdgarIdentity.exchange must be non-empty")
        if not str(self.us_ticker).strip():
            raise ValueError("CaEdgarIdentity.us_ticker must be non-empty")
        if int(self.cik) <= 0:
            raise ValueError("CaEdgarIdentity.cik must be positive")
        object.__setattr__(self, "ca_ticker", ticker)
        object.__setattr__(self, "exchange", str(self.exchange).strip().upper())
        object.__setattr__(self, "us_ticker", str(self.us_ticker).strip().upper())
        object.__setattr__(self, "cik", int(self.cik))
        object.__setattr__(self, "issuer", str(self.issuer).strip())
        object.__setattr__(self, "mapping_source", str(self.mapping_source).strip())
        object.__setattr__(self, "mapping_version", str(self.mapping_version).strip())


@dataclass(frozen=True)
class CaEdgarCollectionFailure:
    """A failed CA ticker that must not discard independent successes."""

    ticker: str
    message: str


class CaEdgarConnector:
    """Collect a narrow set of EDGAR forms for explicitly mapped CA listings."""

    name = "ca_edgar"
    provider = "US SEC EDGAR (Canadian cross-listing fallback; not SEDAR+)"
    coverage_level = "tier_1_us_regulatory_non_sedar"
    coverage_kind = "complete_window"
    source_type = "regulatory_filing"

    def __init__(
        self,
        *,
        client: JSONClient,
        identities: Iterable[CaEdgarIdentity] = (),
    ) -> None:
        self._client = client
        self._identities = tuple(identities)
        self._last_errors: Tuple[CaEdgarCollectionFailure, ...] = ()
        self.last_collection_status = "empty"
        self.last_records_read = 0

    @classmethod
    def configuration_error(cls) -> Optional[str]:
        """Return a truthful disabled reason without constructing a client."""
        raw_path = os.environ.get(IDENTITY_PATH_ENV, "").strip()
        missing = []
        if not os.environ.get("SEC_USER_AGENT", "").strip():
            missing.append("SEC_USER_AGENT")
        if not raw_path:
            missing.append(IDENTITY_PATH_ENV)
        if missing:
            return (
                f"{', '.join(missing)} is not configured; CA EDGAR requires "
                "an identified SEC client and explicit reviewed identity mappings."
            )
        path = Path(raw_path)
        if not path.is_file():
            return f"{IDENTITY_PATH_ENV} is not a readable mapping file: {path}"
        return None

    @classmethod
    def from_environment(cls) -> "CaEdgarConnector":
        """Load reviewed identities and reuse the SEC client's env contract."""
        error = cls.configuration_error()
        if error is not None:
            raise ConnectorUnavailableError(error)
        path = Path(os.environ[IDENTITY_PATH_ENV])
        try:
            identities = load_identities_from_path(path)
            client = SECClient.from_environment()
        except Exception as error:
            raise ConnectorUnavailableError(
                f"CA EDGAR is not connected: {error}"
            ) from error
        return cls(client=client, identities=identities)

    @property
    def last_errors(self) -> Tuple[CaEdgarCollectionFailure, ...]:
        return self._last_errors

    def collect(self, request: CollectionRequest) -> List[InformationItem]:
        requested = tuple(dict.fromkeys(
            (normalize_ca_ticker(ticker), infer_ca_board(ticker))
            for ticker in request.tickers
            if self._is_ca_request(request, ticker)
        ))
        if not requested:
            self._last_errors = ()
            self.last_collection_status = "empty"
            self.last_records_read = 0
            return []

        collected_at = datetime.now(timezone.utc)
        items: List[InformationItem] = []
        failures: List[CaEdgarCollectionFailure] = []
        records_read = 0
        successful_tickers = 0
        for ticker, exchange in requested:
            try:
                identity = self._resolve_identity(ticker, exchange=exchange)
                ticker_items, ticker_records_read = self._collect_identity(
                    identity,
                    start_date=request.start_date,
                    end_date=request.end_date,
                    collected_at=collected_at,
                )
                items.extend(ticker_items)
                records_read += ticker_records_read
                successful_tickers += 1
            except Exception as error:
                failures.append(CaEdgarCollectionFailure(
                    ticker=ticker,
                    message=str(error) or error.__class__.__name__,
                ))

        self._last_errors = tuple(failures)
        self.last_records_read = records_read
        if failures:
            self.last_collection_status = (
                "partial" if successful_tickers else "unavailable"
            )
        else:
            self.last_collection_status = "success" if items else "empty"
        return items

    @staticmethod
    def _is_ca_request(request: CollectionRequest, original_ticker: str) -> bool:
        # Imported CA lists sometimes retain the user suffix in ``markets``
        # while the CA normalizer produces the root.  Either explicit spelling
        # is acceptable; an absent market is never assumed to be Canada.
        return bool(
            request.market_for(original_ticker) == MARKET_CA
            or request.market_for(normalize_ca_ticker(original_ticker)) == MARKET_CA
        )

    def _resolve_identity(
        self, ticker: str, *, exchange: Optional[str] = None
    ) -> CaEdgarIdentity:
        matches = tuple(
            identity for identity in self._identities
            if identity.ca_ticker == ticker
            and (exchange is None or identity.exchange == exchange)
        )
        if not matches:
            raise CaEdgarDataError(
                "No explicit CA ticker/exchange to EDGAR mapping for "
                f"{ticker}{f' on {exchange}' if exchange else ''}"
            )
        if len(matches) != 1:
            exchanges = ", ".join(sorted(identity.exchange for identity in matches))
            raise CaEdgarDataError(
                f"Conflicting CA EDGAR mappings for {ticker}: {exchanges}"
            )
        return matches[0]

    def _collect_identity(
        self,
        identity: CaEdgarIdentity,
        *,
        start_date: date,
        end_date: date,
        collected_at: datetime,
    ) -> Tuple[List[InformationItem], int]:
        submission_url = _submission_url(identity.cik)
        payload = self._client.get_json(submission_url)
        _verify_identity_against_submission(payload, identity)
        issuer = _company_name(payload) or identity.issuer
        if not issuer:
            raise CaEdgarDataError(
                f"SEC submissions response has no issuer name for CIK {identity.cik:010d}"
            )
        records_read = 0
        items: List[InformationItem] = []
        for table in self._filing_tables_for_range(payload, start_date, end_date):
            table_items, table_records_read = self._map_filing_table(
                table,
                identity=identity,
                issuer=issuer,
                start_date=start_date,
                end_date=end_date,
                collected_at=collected_at,
                submission_url=submission_url,
            )
            records_read += table_records_read
            items.extend(table_items)
        return items, records_read

    def _filing_tables_for_range(
        self,
        payload: Any,
        start_date: date,
        end_date: date,
    ) -> Iterable[Mapping[str, Any]]:
        if not isinstance(payload, Mapping):
            raise CaEdgarDataError("SEC submissions response must be a JSON object")
        try:
            filings = payload["filings"]
            recent = filings["recent"]
            historical_files = filings.get("files", [])
        except (KeyError, TypeError) as error:
            raise CaEdgarDataError(
                "SEC submissions response has an unexpected structure"
            ) from error
        if not isinstance(recent, Mapping) or not isinstance(historical_files, list):
            raise CaEdgarDataError("SEC submissions filing tables have an unexpected structure")
        yield recent
        for record in historical_files:
            if not isinstance(record, Mapping):
                raise CaEdgarDataError("SEC historical submissions entry is not an object")
            if not _historical_file_overlaps(record, start_date, end_date):
                continue
            file_name = record.get("name")
            if not isinstance(file_name, str) or not file_name.strip():
                raise CaEdgarDataError("SEC historical submissions entry has no name")
            historical = self._client.get_json(f"{SUBMISSIONS_BASE_URL}/{file_name}")
            if not isinstance(historical, Mapping):
                raise CaEdgarDataError(
                    f"SEC historical submissions file is invalid: {file_name}"
                )
            yield historical

    def _map_filing_table(
        self,
        table: Mapping[str, Any],
        *,
        identity: CaEdgarIdentity,
        issuer: str,
        start_date: date,
        end_date: date,
        collected_at: datetime,
        submission_url: str,
    ) -> Tuple[List[InformationItem], int]:
        columns = _validated_columns(table)
        row_count = len(columns["accessionNumber"])
        items: List[InformationItem] = []
        for index in range(row_count):
            filing_date = _filing_date(columns["filingDate"][index])
            if not start_date <= filing_date <= end_date:
                continue
            form = str(columns["form"][index] or "").strip().upper()
            if form not in ALLOWED_FORMS:
                continue
            accession = str(columns["accessionNumber"][index]).strip()
            if not accession:
                raise CaEdgarDataError("SEC filing row has no accession number")
            primary_document = str(columns["primaryDocument"][index] or "").strip()
            description = str(columns["primaryDocDescription"][index] or "").strip()
            document_url = _filing_url(identity.cik, accession, primary_document)
            directory_url = _filing_directory_url(identity.cik, accession)
            index_url = f"{directory_url}/index.json"
            accession_url = f"{directory_url}/{accession}-index.html"
            index_payload = self._client.get_json(index_url)
            attachments = _attachment_urls(index_payload, directory_url, document_url)
            acceptance = _effective_datetime(
                table.get("acceptanceDateTime"), index
            )
            raw_record = {
                "submissions_row": _raw_submission_row(table, index),
                "attachment_index": index_payload,
                "identity": {
                    "ca_ticker": identity.ca_ticker,
                    "exchange": identity.exchange,
                    "us_ticker": identity.us_ticker,
                    "cik": f"{identity.cik:010d}",
                    "mapping_source": identity.mapping_source,
                    "mapping_version": identity.mapping_version,
                },
            }
            filing_type = _ca_filing_type(form, description)
            metadata = {
                **build_raw_provenance(
                    official_source_id=accession,
                    official_source_url=accession_url,
                    retrieval_url=index_url,
                    raw_payload=raw_record,
                    raw_payload_format="json",
                    classification_code=form,
                    classification_label=description or form,
                    published_at_raw=filing_date.isoformat(),
                    published_timezone="UTC",
                    revision_semantics="amendment" if form.endswith("/A") else "original",
                ),
                "source_tier": 1,
                "source_tier_label": "us_regulator",
                "source_role": "us_regulatory_fallback",
                "is_official": True,
                "officiality": "US_regulatory_filing",
                "cross_verified": False,
                "attachments_may_be_missing": False,
                "regulatory_jurisdiction": "US",
                "non_sedar": True,
                "coverage_level": self.coverage_level,
                "cik": f"{identity.cik:010d}",
                "ca_ticker": identity.ca_ticker,
                "exchange": identity.exchange,
                "us_ticker": identity.us_ticker,
                "mapping_source": identity.mapping_source,
                "mapping_version": identity.mapping_version,
                "accession_number": accession,
                "accession_url": accession_url,
                "document_url": document_url,
                "index_url": index_url,
                "attachments": attachments,
                "filing_type": filing_type,
                "sec_form": form,
            }
            items.append(InformationItem(
                source=self.name,
                source_type="regulatory_filing",
                external_id=f"sec:{identity.cik:010d}:{accession}",
                tickers=(identity.ca_ticker,),
                issuer=issuer,
                published_at=datetime.combine(
                    filing_date, datetime.min.time(), tzinfo=timezone.utc
                ),
                title=description or _fallback_title(form),
                document_type=filing_type,
                url=document_url,
                collected_at=collected_at,
                raw_metadata=metadata,
                market=MARKET_CA,
                effective_at=acceptance,
            ))
        return items, row_count


def _validated_columns(table: Mapping[str, Any]) -> Mapping[str, Sequence[Any]]:
    required = (
        "accessionNumber", "filingDate", "form", "primaryDocument",
        "primaryDocDescription",
    )
    try:
        columns = {name: table[name] for name in required}
    except KeyError as error:
        raise CaEdgarDataError(
            f"SEC filing table is missing column: {error.args[0]}"
        ) from error
    if any(not isinstance(value, list) for value in columns.values()):
        raise CaEdgarDataError("SEC filing table columns must be arrays")
    count = len(columns["accessionNumber"])
    if any(len(value) != count for value in columns.values()):
        raise CaEdgarDataError("SEC filing table columns have different lengths")
    return columns


def load_identities_from_path(path: Path) -> Tuple[CaEdgarIdentity, ...]:
    """Load a reviewed mapping file; reject schema drift and ambiguous input.

    The file is deliberately a local, free configuration artifact rather than
    a ticker/name lookup service.  It must be a JSON object with exactly a
    ``schema`` marker and an ``identities`` list, so accidental provider
    payloads cannot silently enable a wrong fallback.
    """
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise CaEdgarDataError(f"Could not read CA EDGAR identity mapping: {path}") from error
    if not isinstance(payload, Mapping) or set(payload) != {"schema", "identities"}:
        raise CaEdgarDataError(
            "CA EDGAR identity mapping must contain exactly schema and identities"
        )
    if payload.get("schema") != IDENTITY_SCHEMA:
        raise CaEdgarDataError(
            f"CA EDGAR identity mapping schema must be {IDENTITY_SCHEMA!r}"
        )
    raw_identities = payload.get("identities")
    if not isinstance(raw_identities, list) or not raw_identities:
        raise CaEdgarDataError("CA EDGAR identity mapping must contain identities")
    required = {"ca_ticker", "exchange", "us_ticker", "cik"}
    optional = {"issuer", "mapping_source", "mapping_version"}
    identities: List[CaEdgarIdentity] = []
    for index, raw_identity in enumerate(raw_identities):
        if not isinstance(raw_identity, Mapping):
            raise CaEdgarDataError(
                f"CA EDGAR identity at index {index} must be an object"
            )
        keys = set(raw_identity)
        if not required.issubset(keys) or keys - required - optional:
            raise CaEdgarDataError(
                f"CA EDGAR identity at index {index} has an invalid field set"
            )
        try:
            identities.append(CaEdgarIdentity(
                ca_ticker=_required_text(raw_identity, "ca_ticker", index),
                exchange=_required_text(raw_identity, "exchange", index),
                us_ticker=_required_text(raw_identity, "us_ticker", index),
                cik=_required_cik(raw_identity, index),
                issuer=_optional_text(raw_identity.get("issuer"), "issuer", index),
                mapping_source=_optional_text(
                    raw_identity.get("mapping_source"), "mapping_source", index
                ) or "manual_review",
                mapping_version=_optional_text(
                    raw_identity.get("mapping_version"), "mapping_version", index
                ) or "1",
            ))
        except (TypeError, ValueError) as error:
            raise CaEdgarDataError(
                f"CA EDGAR identity at index {index} is invalid: {error}"
            ) from error
    return tuple(identities)


def _required_text(record: Mapping[str, Any], field: str, index: int) -> str:
    value = record.get(field)
    if not isinstance(value, str) or not value.strip():
        raise CaEdgarDataError(
            f"CA EDGAR identity at index {index} has no valid {field}"
        )
    return value


def _optional_text(value: Any, field: str, index: int) -> str:
    if value is None:
        return ""
    if not isinstance(value, str):
        raise CaEdgarDataError(
            f"CA EDGAR identity at index {index} has no valid {field}"
        )
    return value


def _required_cik(record: Mapping[str, Any], index: int) -> int:
    value = record.get("cik")
    if isinstance(value, bool) or not isinstance(value, (int, str)):
        raise CaEdgarDataError(
            f"CA EDGAR identity at index {index} has no valid cik"
        )
    try:
        return int(value)
    except (TypeError, ValueError) as error:
        raise CaEdgarDataError(
            f"CA EDGAR identity at index {index} has no valid cik"
        ) from error


def _filing_date(value: Any) -> date:
    try:
        return date.fromisoformat(str(value))
    except ValueError as error:
        raise CaEdgarDataError("SEC filingDate is not a valid ISO date") from error


def _filing_directory_url(cik: int, accession: str) -> str:
    digits = accession.replace("-", "")
    if not digits.isdigit():
        raise CaEdgarDataError(f"SEC accession number is invalid: {accession!r}")
    return f"{ARCHIVES_BASE_URL}/{cik}/{digits}"


def _attachment_urls(
    payload: Any,
    directory_url: str,
    document_url: str,
) -> List[str]:
    if not isinstance(payload, Mapping):
        raise CaEdgarDataError("SEC filing index is not a JSON object")
    directory = payload.get("directory")
    entries = directory.get("item") if isinstance(directory, Mapping) else None
    if not isinstance(entries, list):
        raise CaEdgarDataError("SEC filing index has no directory item list")
    attachments: List[str] = []
    for entry in entries:
        if not isinstance(entry, Mapping):
            raise CaEdgarDataError("SEC filing index entry is not an object")
        name = entry.get("name")
        if not isinstance(name, str) or not name.strip():
            raise CaEdgarDataError("SEC filing index entry has no document name")
        if "/" in name or "\\" in name:
            raise CaEdgarDataError("SEC filing index has an unsafe document name")
        url = f"{directory_url}/{name}"
        if url not in attachments:
            attachments.append(url)
    if not attachments:
        raise CaEdgarDataError("SEC filing index has no attachments")
    if document_url not in attachments:
        attachments.insert(0, document_url)
    return attachments


def _company_name(payload: Any) -> str:
    value = payload.get("name") if isinstance(payload, Mapping) else None
    return value.strip() if isinstance(value, str) else ""


def _verify_identity_against_submission(
    payload: Any,
    identity: CaEdgarIdentity,
) -> None:
    """Ensure the reviewed CA→US mapping still agrees with SEC's identity."""
    if not isinstance(payload, Mapping):
        raise CaEdgarDataError("SEC submissions response must be a JSON object")
    raw_tickers = payload.get("tickers")
    if not isinstance(raw_tickers, list):
        raise CaEdgarDataError("SEC submissions response has no ticker list")
    sec_tickers = {
        value.strip().upper()
        for value in raw_tickers
        if isinstance(value, str) and value.strip()
    }
    if identity.us_ticker not in sec_tickers:
        raise CaEdgarDataError(
            "Explicit CA EDGAR mapping disagrees with SEC submissions ticker "
            f"for {identity.ca_ticker}: expected {identity.us_ticker}"
        )


def _raw_submission_row(table: Mapping[str, Any], index: int) -> Mapping[str, Any]:
    return {
        str(key): values[index]
        for key, values in table.items()
        if isinstance(values, list) and index < len(values)
    }


def _fallback_title(form: str) -> str:
    return f"SEC Form {form} filing for Canadian cross-listed issuer"


def _ca_filing_type(form: str, description: str) -> str:
    if form.startswith("40-F") or form.startswith("20-F"):
        return "annual_report"
    if form.startswith("F-10"):
        return "prospectus"
    text = description.casefold()
    if form.startswith("6-K") or form.startswith("8-K"):
        if any(term in text for term in ("earnings", "financial results")):
            return "financial_results"
        if any(term in text for term in ("acquisition", "merger", "disposition")):
            return "acquisition_disposal"
        if any(term in text for term in ("financing", "offering", "debt")):
            return "financing"
        return "material_change"
    return "other_filing"


def _effective_datetime(values: Any, index: int) -> Optional[datetime]:
    if not isinstance(values, list) or index >= len(values):
        return None
    raw = values[index]
    if raw is None:
        return None
    try:
        parsed = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
