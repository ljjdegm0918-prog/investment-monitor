"""SEC EDGAR connector and ticker-to-CIK resolution."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timezone
import json
import logging
import os
from pathlib import Path
import time
from typing import Any, Dict, Iterable, List, Mapping, Optional, Protocol, Tuple

from ...connectors.base import ConnectorUnavailableError, SecretField
from ...models import CollectionRequest, InformationItem, MARKET_US
from .client import SECClient, SECDataError, SECError

LOGGER = logging.getLogger(__name__)

COMPANY_TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"
SUBMISSIONS_BASE_URL = "https://data.sec.gov/submissions"
ARCHIVES_BASE_URL = "https://www.sec.gov/Archives/edgar/data"


class JSONClient(Protocol):
    """The small client surface used by SEC-specific data logic."""

    def get_json(self, url: str) -> Any:
        ...


class SECTickerNotFoundError(SECError):
    """Raised when the SEC ticker mapping does not contain a ticker."""


@dataclass(frozen=True)
class TickerCollectionFailure:
    """A ticker that failed without stopping the rest of the request."""

    ticker: str
    message: str


class TickerCIKResolver:
    """Resolve SEC tickers and maintain a local copy of the official mapping."""

    def __init__(
        self,
        client: JSONClient,
        cache_path: Path,
        cache_ttl_seconds: float = 24 * 60 * 60,
        clock: Any = time.time,
    ) -> None:
        self._client = client
        self._cache_path = cache_path
        self._cache_ttl_seconds = cache_ttl_seconds
        self._clock = clock
        self._mapping: Optional[Dict[str, Tuple[int, str]]] = None

    def resolve(self, ticker: str) -> Tuple[int, str]:
        """Return the numeric CIK and SEC company name for a ticker."""
        mapping = self._load_mapping()
        normalized_ticker = ticker.strip().upper()
        try:
            return mapping[normalized_ticker]
        except KeyError as error:
            raise SECTickerNotFoundError(
                f"Ticker is not present in SEC company_tickers.json: "
                f"{normalized_ticker}"
            ) from error

    def _load_mapping(self) -> Dict[str, Tuple[int, str]]:
        if self._mapping is not None:
            return self._mapping

        cached_payload = self._read_cached_payload()
        if self._cache_is_fresh() and cached_payload is not None:
            try:
                self._mapping = self._parse_mapping(cached_payload)
                return self._mapping
            except SECDataError:
                pass

        try:
            payload = self._download_and_cache()
        except SECError:
            if cached_payload is None:
                raise
            LOGGER.warning(
                "SEC ticker mapping refresh failed; using the existing stale cache: %s",
                self._cache_path,
            )
            payload = cached_payload

        self._mapping = self._parse_mapping(payload)
        return self._mapping

    def _read_cached_payload(self) -> Optional[Any]:
        try:
            with self._cache_path.open("r", encoding="utf-8") as cache_file:
                return json.load(cache_file)
        except (OSError, json.JSONDecodeError):
            return None

    def _cache_is_fresh(self) -> bool:
        try:
            age = float(self._clock()) - self._cache_path.stat().st_mtime
        except OSError:
            return False
        return 0 <= age <= self._cache_ttl_seconds

    def _download_and_cache(self) -> Any:
        payload = self._client.get_json(COMPANY_TICKERS_URL)
        self._cache_path.parent.mkdir(parents=True, exist_ok=True)
        temporary_path = self._cache_path.with_suffix(
            self._cache_path.suffix + ".tmp"
        )
        try:
            with temporary_path.open("w", encoding="utf-8") as cache_file:
                json.dump(payload, cache_file)
            temporary_path.replace(self._cache_path)
        except OSError as error:
            raise SECDataError(
                f"Could not write SEC ticker cache: {self._cache_path}"
            ) from error
        return payload

    @staticmethod
    def _parse_mapping(payload: Any) -> Dict[str, Tuple[int, str]]:
        if not isinstance(payload, dict):
            raise SECDataError("SEC ticker mapping must be a JSON object.")

        mapping: Dict[str, Tuple[int, str]] = {}
        try:
            records = payload.values()
            for record in records:
                ticker = str(record["ticker"]).strip().upper()
                cik = int(record["cik_str"])
                title = str(record["title"]).strip()
                mapping[ticker] = (cik, title)
        except (KeyError, TypeError, ValueError) as error:
            raise SECDataError(
                "SEC ticker mapping has an unexpected structure."
            ) from error
        return mapping


class SECConnector:
    """Collect SEC submission metadata and standardize it."""

    name = "sec"
    secret_fields = (
        SecretField(
            env="SEC_USER_AGENT",
            label="SEC User-Agent",
            kind="text",
            help=(
                "SEC asks automated clients to identify the application and "
                "provide a contact address (for example "
                "InvestmentMonitor/0.1 name@example.com)."
            ),
        ),
    )

    def __init__(
        self,
        client: JSONClient,
        resolver: TickerCIKResolver,
    ) -> None:
        self._client = client
        self._resolver = resolver
        self._last_errors: Tuple[TickerCollectionFailure, ...] = ()

    @classmethod
    def from_environment(cls) -> "SECConnector":
        """Build a production connector from environment configuration."""
        configuration_error = cls.configuration_error()
        if configuration_error is not None:
            raise ConnectorUnavailableError(configuration_error)
        client = SECClient.from_environment()
        cache_path = Path(
            os.environ.get(
                "SEC_TICKER_CACHE_PATH",
                ".cache/investment_monitor/company_tickers.json",
            )
        )
        cache_ttl_seconds = _read_cache_ttl()
        resolver = TickerCIKResolver(
            client=client,
            cache_path=cache_path,
            cache_ttl_seconds=cache_ttl_seconds,
        )
        return cls(client=client, resolver=resolver)

    @classmethod
    def configuration_error(cls) -> Optional[str]:
        """Return a reason when the source cannot be enabled."""
        if not os.environ.get("SEC_USER_AGENT", "").strip():
            return (
                "SEC_USER_AGENT is not configured; SEC is not connected."
            )
        return None

    @property
    def last_errors(self) -> Tuple[TickerCollectionFailure, ...]:
        """Errors from the most recent collect call."""
        return self._last_errors

    def collect(self, request: CollectionRequest) -> List[InformationItem]:
        """Collect filings for each ticker, allowing partial success."""
        items: List[InformationItem] = []
        failures: List[TickerCollectionFailure] = []
        collected_at = datetime.now(timezone.utc)

        for ticker in request.tickers:
            market = request.market_for(ticker)
            if market not in ("us", "unknown"):
                failures.append(
                    TickerCollectionFailure(
                        ticker=ticker,
                        message=(
                            f"SEC connector does not cover market "
                            f"'{market}'"
                        ),
                    )
                )
                continue
            try:
                cik, mapped_issuer = self._resolver.resolve(ticker)
                payload = self._client.get_json(_submission_url(cik))
                issuer = _company_name(payload) or mapped_issuer
                tables = list(
                    self._filing_tables_for_range(
                        payload, request.start_date, request.end_date
                    )
                )
                for table in tables:
                    items.extend(
                        _map_filing_table(
                            table=table,
                            ticker=ticker,
                            cik=cik,
                            issuer=issuer,
                            start_date=request.start_date,
                            end_date=request.end_date,
                            collected_at=collected_at,
                        )
                    )
            except Exception as error:
                message = str(error) or error.__class__.__name__
                failures.append(
                    TickerCollectionFailure(ticker=ticker, message=message)
                )
                LOGGER.warning("SEC collection failed for %s: %s", ticker, message)

        self._last_errors = tuple(failures)
        if len(request.tickers) == 1 and failures:
            raise SECError(failures[0].message)
        return items

    def _filing_tables_for_range(
        self,
        payload: Any,
        start_date: date,
        end_date: date,
    ) -> Iterable[Mapping[str, Any]]:
        if not isinstance(payload, dict):
            raise SECDataError("SEC submissions response must be a JSON object.")

        try:
            filings = payload["filings"]
            recent = filings["recent"]
            historical_files = filings.get("files", [])
        except (KeyError, TypeError) as error:
            raise SECDataError(
                "SEC submissions response has an unexpected structure."
            ) from error

        if not isinstance(recent, dict) or not isinstance(historical_files, list):
            raise SECDataError(
                "SEC submissions filing tables have an unexpected structure."
            )

        yield recent

        for file_record in historical_files:
            if not isinstance(file_record, dict):
                continue
            if not _historical_file_overlaps(
                file_record, start_date=start_date, end_date=end_date
            ):
                continue
            file_name = file_record.get("name")
            if not isinstance(file_name, str) or not file_name:
                continue
            historical_payload = self._client.get_json(
                f"{SUBMISSIONS_BASE_URL}/{file_name}"
            )
            if not isinstance(historical_payload, dict):
                raise SECDataError(
                    f"SEC historical submissions file is invalid: {file_name}"
                )
            yield historical_payload


def _map_filing_table(
    table: Mapping[str, Any],
    ticker: str,
    cik: int,
    issuer: str,
    start_date: date,
    end_date: date,
    collected_at: datetime,
) -> List[InformationItem]:
    required_columns = (
        "accessionNumber",
        "filingDate",
        "form",
        "primaryDocument",
        "primaryDocDescription",
    )
    try:
        columns = {name: table[name] for name in required_columns}
    except KeyError as error:
        raise SECDataError(
            f"SEC filing table is missing column: {error.args[0]}"
        ) from error

    if any(not isinstance(value, list) for value in columns.values()):
        raise SECDataError("SEC filing table columns must be arrays.")

    row_count = len(columns["accessionNumber"])
    if any(len(value) != row_count for value in columns.values()):
        raise SECDataError("SEC filing table columns have different lengths.")

    optional_columns = (
        "reportDate",
        "acceptanceDateTime",
        "fileNumber",
        "filmNumber",
        "act",
    )
    items: List[InformationItem] = []

    for index in range(row_count):
        try:
            filing_date = date.fromisoformat(str(columns["filingDate"][index]))
        except ValueError as error:
            raise SECDataError("SEC filingDate is not a valid ISO date.") from error

        if not start_date <= filing_date <= end_date:
            continue

        accession_number = str(columns["accessionNumber"][index])
        form = str(columns["form"][index]).strip()
        primary_document = str(columns["primaryDocument"][index]).strip()
        description = str(columns["primaryDocDescription"][index]).strip()
        metadata: Dict[str, Any] = {
            "cik": str(cik).zfill(10),
            "accessionNumber": accession_number,
            "filingDate": filing_date.isoformat(),
            "primaryDocument": primary_document,
            "primaryDocDescription": description,
        }
        for column_name in optional_columns:
            values = table.get(column_name)
            if isinstance(values, list) and index < len(values):
                metadata[column_name] = values[index]

        items.append(
            InformationItem(
                source="sec",
                source_type="regulatory_filing",
                external_id=accession_number,
                tickers=(ticker,),
                issuer=issuer,
                published_at=datetime.combine(
                    filing_date, datetime.min.time(), tzinfo=timezone.utc
                ),
                title=description or _fallback_title(form),
                document_type=form,
                url=_filing_url(cik, accession_number, primary_document),
                collected_at=collected_at,
                raw_metadata=metadata,
                market=MARKET_US,
                effective_at=_effective_datetime(
                    columns.get("acceptanceDateTime"),
                    index,
                ),
            )
        )

    return items


def _submission_url(cik: int) -> str:
    return f"{SUBMISSIONS_BASE_URL}/CIK{cik:010d}.json"


def _filing_url(cik: int, accession_number: str, primary_document: str) -> str:
    accession_without_dashes = accession_number.replace("-", "")
    document = primary_document or f"{accession_number}-index.html"
    return (
        f"{ARCHIVES_BASE_URL}/{cik}/{accession_without_dashes}/{document}"
    )


def _fallback_title(form: str) -> str:
    readable_forms = {
        "10-K": "Form 10-K Annual Report",
        "10-K/A": "Form 10-K/A Amended Annual Report",
        "10-Q": "Form 10-Q Quarterly Report",
        "10-Q/A": "Form 10-Q/A Amended Quarterly Report",
        "8-K": "Form 8-K Current Report",
        "8-K/A": "Form 8-K/A Amended Current Report",
    }
    return readable_forms.get(form, f"SEC Form {form} Filing")


def _company_name(payload: Mapping[str, Any]) -> str:
    name = payload.get("name")
    return name.strip() if isinstance(name, str) else ""


def _historical_file_overlaps(
    record: Mapping[str, Any],
    start_date: date,
    end_date: date,
) -> bool:
    try:
        filing_from = date.fromisoformat(str(record["filingFrom"]))
        filing_to = date.fromisoformat(str(record["filingTo"]))
    except (KeyError, ValueError):
        return False
    return filing_from <= end_date and filing_to >= start_date


def _read_cache_ttl() -> float:
    value = os.environ.get("SEC_TICKER_CACHE_TTL_SECONDS")
    if value is None:
        return 24 * 60 * 60
    try:
        result = float(value)
    except ValueError as error:
        raise SECDataError(
            "SEC_TICKER_CACHE_TTL_SECONDS must be a number."
        ) from error
    if result < 0:
        raise SECDataError(
            "SEC_TICKER_CACHE_TTL_SECONDS must not be negative."
        )
    return result


def _effective_datetime(values: Any, index: int) -> Optional[datetime]:
    """Parse SEC acceptanceDateTime into a timezone-aware datetime."""
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
