"""Collect filings from the public first-party CSE issuer data service.

The CSE security JSON identifies the exchange-listed issuer and supplies the
issuer's CSE-hosted filing-list URL.  This connector follows only that exact
first-party link.  It never requests SEDAR+ and does not claim TSX/TSXV or
national completeness.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timezone
import json
import os
from pathlib import Path
import socket
import time as time_module
from typing import Any, Callable, Iterable, List, Mapping, Optional, Tuple
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

from ...ca_universe import CaUniverseError, load_ca_universe, refresh_ca_universe
from ...connectors.base import ConnectorUnavailableError
from ...models import CollectionRequest, InformationItem, MARKET_CA
from ...provenance import build_raw_provenance
from ...web_repository import normalize_ca_ticker


SECURITY_URL = (
    "https://webapi-backup.thecse.com/trading/listed/securities/{symbol}.json"
)
_SECURITY_HOST = "webapi-backup.thecse.com"
_DOCUMENT_HOST = "sedar-filings-backup.thecse.com"
_TORONTO = ZoneInfo("America/Toronto")


class CseFilingRequestError(RuntimeError):
    """The public CSE data service could not be read."""


class CseFilingDataError(RuntimeError):
    """A CSE response failed identity, completeness, or shape validation."""


@dataclass(frozen=True)
class CseIssuerIdentity:
    ticker: str
    issuer_name: str
    symbol: str = ""

    def __post_init__(self) -> None:
        ticker = normalize_ca_ticker(self.ticker)
        symbol = str(self.symbol or ticker).strip().upper()
        issuer = str(self.issuer_name).strip()
        if not ticker or not issuer or not symbol:
            raise ValueError("CSE identity requires ticker, symbol, and issuer_name")
        object.__setattr__(self, "ticker", ticker)
        object.__setattr__(self, "symbol", symbol)
        object.__setattr__(self, "issuer_name", issuer)


class CseFilingsConnector:
    name = "cse_filings"
    provider = "Canadian Securities Exchange public issuer filings"
    source_type = "regulatory_filing"
    coverage_level = "official_exchange_mirror_cse_only"
    coverage_kind = "complete_available_issuer_snapshot"

    def __init__(
        self,
        *,
        identities: Iterable[CseIssuerIdentity],
        fetcher: Optional[Callable[[str], Any]] = None,
        retry_attempts: int = 3,
        sleeper: Callable[[float], None] = time_module.sleep,
    ) -> None:
        rows = tuple(identities)
        grouped: dict[str, list[CseIssuerIdentity]] = {}
        for identity in rows:
            grouped.setdefault(identity.ticker, []).append(identity)
        conflicts = [ticker for ticker, matches in grouped.items() if len(matches) != 1]
        if conflicts:
            raise ValueError(f"Conflicting CSE identities: {', '.join(sorted(conflicts))}")
        self._identities = {identity.ticker: identity for identity in rows}
        self._fetcher = fetcher or _fetch_json
        self._retry_attempts = max(1, int(retry_attempts))
        self._sleeper = sleeper
        self._last_errors: Tuple[Tuple[str, str], ...] = ()
        self.last_failure_details: Tuple[Mapping[str, str], ...] = ()
        self.last_collection_status = "empty"
        self.last_records_read = 0

    @classmethod
    def configuration_error(cls) -> Optional[str]:
        try:
            _load_identities()
        except (OSError, ValueError, CseFilingDataError) as error:
            return f"CSE filing identity cache is invalid: {error}"
        return None

    @classmethod
    def from_environment(cls) -> "CseFilingsConnector":
        error = cls.configuration_error()
        if error:
            raise ConnectorUnavailableError(error)
        identities = _load_identities()
        if not identities:
            try:
                refresh_ca_universe()
            except (CaUniverseError, OSError, ValueError) as refresh_error:
                raise ConnectorUnavailableError(
                    f"CSE universe refresh failed: {refresh_error}"
                ) from refresh_error
            identities = _load_identities()
        if not identities:
            raise ConnectorUnavailableError(
                "CSE universe refresh returned no CSE identities."
            )
        return cls(identities=identities)

    @property
    def last_errors(self) -> Tuple[Tuple[str, str], ...]:
        return self._last_errors

    def collect(self, request: CollectionRequest) -> List[InformationItem]:
        targets = tuple(dict.fromkeys(
            normalize_ca_ticker(ticker)
            for ticker in request.tickers
            if request.market_for(ticker) == MARKET_CA
        ))
        selected = [self._identities[ticker] for ticker in targets if ticker in self._identities]
        if not selected:
            self._set_status("empty", (), 0)
            return []
        items: List[InformationItem] = []
        errors: List[Tuple[str, str]] = []
        records_read = 0
        collected_at = datetime.now(timezone.utc)
        for index, identity in enumerate(selected):
            if index:
                self._sleeper(0.25)
            try:
                mapped, read = self._collect_issuer(
                    identity, request.start_date, request.end_date, collected_at
                )
                items.extend(mapped)
                records_read += read
            except Exception as error:  # one issuer must not erase other CSE results
                errors.append((identity.ticker, str(error) or error.__class__.__name__))
        status = "partial" if errors and items else "unavailable" if errors else "success" if items else "empty"
        self._set_status(status, errors, records_read)
        return items

    def _collect_issuer(
        self,
        identity: CseIssuerIdentity,
        start: date,
        end: date,
        collected_at: datetime,
    ) -> Tuple[List[InformationItem], int]:
        security_url = SECURITY_URL.format(symbol=identity.symbol)
        security = self._retry_fetch(security_url)
        metadata = security.get("metadata") if isinstance(security, Mapping) else None
        if not isinstance(metadata, Mapping):
            raise CseFilingDataError("CSE security response has no metadata object")
        if str(metadata.get("listing_market") or "").upper() != "CSE":
            raise CseFilingDataError("CSE security response has the wrong listing market")
        if str(metadata.get("symbol") or "").upper() != identity.symbol:
            raise CseFilingDataError("CSE security response symbol does not match the request")
        response_name = str(metadata.get("security_name") or "").strip()
        if not response_name or _name_key(response_name) != _name_key(identity.issuer_name):
            raise CseFilingDataError("CSE security response issuer identity mismatch")
        filings_url = _filings_url(metadata.get("sedar_filings"))
        payload = self._retry_fetch(filings_url)
        rows = _validated_rows(payload)
        output: List[InformationItem] = []
        for row in rows:
            published_day = _date(row.get("public_date"))
            if not start <= published_day <= end:
                continue
            output.append(_to_item(
                row, identity, filings_url, security_url, published_day, collected_at
            ))
        return output, len(rows)

    def _retry_fetch(self, url: str) -> Mapping[str, Any]:
        for attempt in range(self._retry_attempts):
            try:
                payload = self._fetcher(url)
                if not isinstance(payload, Mapping):
                    raise CseFilingDataError("CSE endpoint did not return a JSON object")
                return payload
            except CseFilingRequestError as error:
                if any(code in str(error) for code in ("HTTP 403", "HTTP 429")):
                    raise
                if attempt + 1 >= self._retry_attempts:
                    raise
                self._sleeper(min(2 ** attempt, 4))
        raise CseFilingRequestError("CSE retry loop ended unexpectedly")

    def _set_status(
        self, status: str, errors: Iterable[Tuple[str, str]], records_read: int
    ) -> None:
        self.last_collection_status = status
        self._last_errors = tuple(errors)
        self.last_records_read = records_read
        self.last_failure_details = tuple({
            "feed": "CSE issuer filings",
            "ticker": ticker,
            "message": message,
        } for ticker, message in self._last_errors)


def _load_identities() -> Tuple[CseIssuerIdentity, ...]:
    path_value = os.environ.get("CA_UNIVERSE_CACHE_PATH", "").strip()
    payload = load_ca_universe(Path(path_value) if path_value else None)
    if not payload:
        return ()
    rows = payload.get("items")
    if not isinstance(rows, list):
        raise CseFilingDataError("CA universe cache has no items list")
    identities = []
    for row in rows:
        if not isinstance(row, Mapping) or str(row.get("exchange") or "").upper() != "CSE":
            continue
        identities.append(CseIssuerIdentity(
            ticker=str(row.get("ticker") or row.get("symbol") or ""),
            symbol=str(row.get("symbol") or row.get("ticker") or ""),
            issuer_name=str(row.get("issuer_name") or row.get("name") or ""),
        ))
    return tuple(identities)


def _fetch_json(url: str) -> Mapping[str, Any]:
    parsed = urlparse(url)
    if parsed.scheme != "https" or parsed.hostname not in {_SECURITY_HOST, _DOCUMENT_HOST}:
        raise CseFilingDataError("CSE request URL was outside the first-party allowlist")
    request = Request(url, headers={
        "User-Agent": "InvestmentMonitor/0.1 cse-filings",
        "Accept": "application/json",
    })
    try:
        with urlopen(request, timeout=20) as response:  # nosec B310 exact host allowlist
            decoded = json.loads(response.read().decode("utf-8"))
    except HTTPError as error:
        raise CseFilingRequestError(f"HTTP {error.code}") from error
    except (URLError, TimeoutError, socket.timeout, OSError) as error:
        raise CseFilingRequestError(str(error) or error.__class__.__name__) from error
    except (UnicodeError, json.JSONDecodeError) as error:
        raise CseFilingDataError("CSE endpoint returned malformed JSON") from error
    if not isinstance(decoded, Mapping):
        raise CseFilingDataError("CSE endpoint returned a non-object payload")
    return decoded


def _filings_url(value: Any) -> str:
    parsed = urlparse(str(value or "").strip())
    if (
        parsed.scheme != "https"
        or parsed.hostname != _SECURITY_HOST
        or not parsed.path.startswith("/trading/listed/sedar_filings/")
        or not parsed.path.endswith(".json")
        or not parsed.path.rsplit("/", 1)[-1][:-5].isdigit()
        or parsed.query
    ):
        raise CseFilingDataError("CSE security response has no valid filing-list URL")
    return parsed.geturl()


def _validated_rows(payload: Mapping[str, Any]) -> List[Mapping[str, Any]]:
    categories = payload.get("categories")
    rows = payload.get("list")
    if not isinstance(categories, Mapping) or not isinstance(rows, list):
        raise CseFilingDataError("CSE filing response shape changed")
    try:
        expected = sum(int(value) for value in categories.values())
    except (TypeError, ValueError) as error:
        raise CseFilingDataError("CSE category counts are invalid") from error
    if expected != len(rows):
        raise CseFilingDataError("CSE filing category count does not match the list")
    result: List[Mapping[str, Any]] = []
    seen: set[str] = set()
    for row in rows:
        if not isinstance(row, Mapping):
            raise CseFilingDataError("CSE filing row is not an object")
        url = _document_url(row.get("url"))
        identity = str(row.get("accession_number") or url).strip()
        status = str(row.get("status") or "").strip().lower()
        if not identity or identity in seen:
            raise CseFilingDataError("CSE filing list contains duplicate identities")
        if status not in {"available", "removed"}:
            raise CseFilingDataError("CSE filing row has an unknown status")
        if not str(row.get("document_description") or "").strip():
            raise CseFilingDataError("CSE filing row has no document description")
        _date(row.get("public_date"))
        seen.add(identity)
        result.append(dict(row, url=url))
    return result


def _document_url(value: Any) -> str:
    parsed = urlparse(str(value or "").strip())
    if (
        parsed.scheme != "https"
        or parsed.hostname != _DOCUMENT_HOST
        or not parsed.path.lower().endswith(".pdf")
    ):
        raise CseFilingDataError("CSE filing document URL is invalid")
    return parsed.geturl()


def _date(value: Any) -> date:
    try:
        return date.fromisoformat(str(value or ""))
    except ValueError as error:
        raise CseFilingDataError("CSE filing public_date is invalid") from error


def _to_item(
    row: Mapping[str, Any],
    identity: CseIssuerIdentity,
    filings_url: str,
    security_url: str,
    published_day: date,
    collected_at: datetime,
) -> InformationItem:
    url = str(row["url"])
    accession = str(row.get("accession_number") or "").strip()
    document_id = accession or urlparse(url).path.rsplit("/", 1)[-1]
    title = _human_title(row.get("document_description"))
    category = str(row.get("document_category") or "")
    filing_type = _filing_type(category, title)
    status = str(row.get("status") or "").lower()
    published_at = datetime.combine(published_day, time(12), tzinfo=_TORONTO)
    canonical_key = f"sedar-accession:{accession}" if accession else f"cse-document:{document_id}"
    metadata = {
        **build_raw_provenance(
            official_source_id=document_id,
            official_source_url=url,
            retrieval_url=filings_url,
            raw_payload=dict(row),
            raw_payload_format="json",
            classification_code=category,
            classification_label=filing_type,
            published_at_raw=published_day.isoformat(),
            published_timezone="America/Toronto",
            revision_semantics="withdrawal" if status == "removed" else "original",
        ),
        "source_tier": 1,
        "source_tier_label": "official_exchange",
        "source_name": "cse",
        "exchange": "CSE",
        "official_document": True,
        "officiality": "official_CSE_hosted_regulatory_filing_mirror",
        "mirror": True,
        "not_sedar_plus_primary": True,
        "coverage_level": CseFilingsConnector.coverage_level,
        "canonical_key": canonical_key,
        "accession_number": accession,
        "document_status": status,
        "filing_description": str(row.get("filing_description") or ""),
        "language": str(row.get("document_language") or "und"),
        "source_url": url,
        "document_url": url,
        "attachment_urls": [url],
        "attachments": [url],
        "security_retrieval_url": security_url,
        "filing_list_retrieval_url": filings_url,
        "collection_status": "success",
        "cross_verified": False,
        "filing_type": filing_type,
    }
    return InformationItem(
        source="cse_filings",
        source_type="regulatory_filing",
        external_id=f"cse:{document_id}",
        tickers=(identity.ticker,),
        issuer=identity.issuer_name,
        published_at=published_at,
        title=title,
        document_type=filing_type,
        url=url,
        collected_at=collected_at,
        raw_metadata=metadata,
        market=MARKET_CA,
        effective_at=published_at,
    )


def _name_key(value: str) -> str:
    return "".join(character for character in value.casefold() if character.isalnum())


def _human_title(value: Any) -> str:
    return " ".join(str(value or "").replace("_", " ").split()).strip()


def _filing_type(category: str, title: str) -> str:
    text = f"{category} {title}".casefold()
    rules = (
        ("technical_report", ("technical report", "43-101")),
        ("prospectus", ("prospectus",)),
        ("material_change", ("material change",)),
        ("annual_report", ("annual financial", "annual mda", "annual report")),
        ("interim_report", ("interim financial", "interim mda")),
        ("financial_results", ("financial statements", "financial statement")),
        ("financing", ("exempt distribution", "private placement", "financing")),
        ("management_change", ("appointment", "resignation", "director", "officer")),
        ("share_buyback", ("issuer bid", "ncib", "share buyback")),
        ("dividend", ("dividend", "distribution")),
        ("acquisition_disposal", ("acquisition", "disposal", "merger")),
    )
    return next((kind for kind, terms in rules if any(term in text for term in terms)), "other_filing")
