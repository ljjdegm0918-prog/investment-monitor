"""Official partial SIX Swiss Exchange share and ETF universe.

SIX's public Share Explorer and ETF Explorer both read the key-free
``/fqs/ref.json`` endpoint.  SIX's public Sponsored Foreign Shares directory
uses the same endpoint with ``TitleSegment=SP``.  This module follows those
public UI requests, reconciles every page against ``totalRows``, and stores metadata only.  It is
not the commercial SIX Reference Data product and the cache is not licensed
for redistribution.

The equity scope includes SIX ``Swiss Shares``, ``Foreign Shares`` and
``Sponsored Foreign Shares``.  Sponsored securities are retained as a
separate type because their primary listing is outside Switzerland.  Routing
MTFs and historical/delisted securities are still outside this issuer master,
so the country-level universe remains partial.
"""

from __future__ import annotations

from datetime import datetime, timezone
from math import ceil
import json
import os
from pathlib import Path
import re
import threading
import time
from typing import Any, Callable, Dict, List, Mapping, Optional, Sequence
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

from ..web_repository import normalize_ch_ticker

DEFAULT_CACHE_PATH = ".cache/investment_monitor/ch_universe.json"
FQS_URL = "https://www.six-group.com/fqs/ref.json"
DEFAULT_USER_AGENT = "InvestmentMonitor/0.1 (internal SIX metadata monitor)"
DEFAULT_PAGE_SIZE = 1000
DEFAULT_MAX_PAGES = 20
RETRYABLE_HTTP_STATUS = frozenset({500, 502, 503, 504})
_ISIN = re.compile(r"[A-Z]{2}[A-Z0-9]{10}")
_SIX_TIME = ZoneInfo("Europe/Zurich")
_SHARE_INSTRUMENT_TYPES = {
    "RS": "equity",
    "BS": "equity",
    "PC": "participation_certificate",
    "RI": "subscription_right",
    "SS": "sponsored_foreign_share",
}

SHARE_COLUMNS = (
    "ShortName",
    "ValorId",
    "ISIN",
    "ValorSymbol",
    "ValorNumber",
    "SecTypeCode",
    "SecTypeDesc",
    "ListingSegmentCode",
    "ListingSegmentDesc",
    "TitleSegment",
    "PortalSegment",
)
SPONSORED_SHARE_COLUMNS = (
    *SHARE_COLUMNS,
    "TradingBaseCurrency",
    "FirstTradingDate",
)
ETF_COLUMNS = (
    "FundLongName",
    "TradingBaseCurrency",
    "FundCurrency",
    "ISIN",
    "ValorId",
    "ValorSymbol",
    "ReplicationMethodDesc",
    "UnderlyingGeographicalDesc",
    "LegalStructureCountryDesc",
    "ManagementFee",
    "ProductLine",
    "PortalSegment",
)

PHASE4_BOUNDARY = {
    "universe": "partial",
    "disclosure": "partial",
    "evidence": (
        "SIX public fqs/ref.json used by Share Explorer and ETF Explorer; "
        "Swiss Shares (SA), Foreign Shares (AA), Sponsored Foreign Shares "
        "(SP), and ETF (ET/FU) scopes"
    ),
}


class ChUniverseError(RuntimeError):
    """Raised when the official SIX directory cannot be validated safely."""


class SixFqsClient:
    """Bounded client for the public JSON requests used by SIX's explorers."""

    def __init__(
        self,
        *,
        opener: Callable[..., Any] = urlopen,
        timeout: float = 20.0,
        max_retries: int = 1,
        requests_per_second: float = 1.0,
        user_agent: str = DEFAULT_USER_AGENT,
        clock: Callable[[], float] = time.monotonic,
        sleeper: Callable[[float], None] = time.sleep,
    ) -> None:
        if timeout <= 0 or max_retries < 0 or requests_per_second <= 0:
            raise ValueError("SIX client limits must be positive")
        self._opener = opener
        self._timeout = timeout
        self._max_retries = max_retries
        self._minimum_interval = 1.0 / requests_per_second
        self._user_agent = user_agent
        self._clock = clock
        self._sleeper = sleeper
        self._last_request_at: Optional[float] = None
        self._lock = threading.Lock()
        self.last_scope_metadata: Mapping[str, Mapping[str, Any]] = {}

    @classmethod
    def from_environment(cls) -> "SixFqsClient":
        return cls(
            timeout=float(os.environ.get("SIX_FQS_TIMEOUT_SECONDS", "20")),
            max_retries=int(os.environ.get("SIX_FQS_MAX_RETRIES", "1")),
            requests_per_second=float(
                os.environ.get("SIX_FQS_REQUESTS_PER_SECOND", "1")
            ),
        )

    def fetch_all(
        self,
        *,
        page_size: int = DEFAULT_PAGE_SIZE,
        max_pages: int = DEFAULT_MAX_PAGES,
    ) -> Mapping[str, Sequence[Mapping[str, Any]]]:
        """Fetch all four required scopes; one failed scope fails the run."""
        scopes: Dict[str, Sequence[Mapping[str, Any]]] = {}
        timings: Dict[str, Mapping[str, Any]] = {}
        for scope, columns, where, order_by, expected in (
            (
                "swiss_shares",
                SHARE_COLUMNS,
                "PortalSegment=EQ*TitleSegment=SA",
                "ShortName",
                {"PortalSegment": "EQ", "TitleSegment": "SA"},
            ),
            (
                "foreign_shares",
                SHARE_COLUMNS,
                "PortalSegment=EQ*TitleSegment=AA",
                "ShortName",
                {"PortalSegment": "EQ", "TitleSegment": "AA"},
            ),
            (
                "sponsored_foreign_shares",
                SPONSORED_SHARE_COLUMNS,
                "PortalSegment=EQ*TitleSegment=SP",
                "ShortName",
                {"PortalSegment": "EQ", "TitleSegment": "SP"},
            ),
            (
                "etfs",
                ETF_COLUMNS,
                "ProductLine=ET*PortalSegment=FU",
                "FundLongName",
                {"ProductLine": "ET", "PortalSegment": "FU"},
            ),
        ):
            rows, timing = self._fetch_scope(
                columns=columns,
                where=where,
                order_by=order_by,
                expected=expected,
                page_size=page_size,
                max_pages=max_pages,
            )
            scopes[scope] = rows
            timings[scope] = timing
        self.last_scope_metadata = timings
        return scopes

    def _fetch_scope(
        self,
        *,
        columns: Sequence[str],
        where: str,
        order_by: str,
        expected: Mapping[str, str],
        page_size: int,
        max_pages: int,
    ) -> tuple[List[Mapping[str, Any]], Mapping[str, Any]]:
        if page_size <= 0 or max_pages <= 0:
            raise ValueError("SIX page limits must be positive")
        records: List[Mapping[str, Any]] = []
        declared_total: Optional[int] = None
        seen_ids: set[str] = set()
        source_millis: List[int] = []
        delay_minutes: Optional[int] = None
        for page in range(1, max_pages + 1):
            params = {
                "select": ",".join(columns),
                "where": where,
                "orderby": order_by,
                "page": str(page),
                "pagesize": str(page_size),
            }
            retrieval_url = FQS_URL + "?" + urlencode(params)
            payload = self._get_json(retrieval_url)
            timing = _fqs_source_timing(payload)
            current_delay = int(timing["delay_minutes"])
            current_millis = int(timing["delayed_millis"])
            if delay_minutes is None:
                delay_minutes = current_delay
            elif current_delay != delay_minutes:
                raise ChUniverseError("SIX FQS delayMinutes drifted between pages")
            if source_millis and current_millis < source_millis[-1]:
                raise ChUniverseError("SIX FQS source time moved backwards")
            source_millis.append(current_millis)
            if not str(payload.get("protocolVersion") or "").startswith("fqs.json#"):
                raise ChUniverseError("SIX FQS protocolVersion is missing or invalid")
            try:
                returned_page = int(payload["pageNumber"])
                returned_size = int(payload["pageSize"])
                total = int(payload["totalRows"])
            except (KeyError, TypeError, ValueError) as error:
                raise ChUniverseError("SIX FQS pagination fields are invalid") from error
            if returned_page != page or returned_size != page_size or total < 0:
                raise ChUniverseError("SIX FQS pagination does not match the request")
            if declared_total is None:
                declared_total = total
            elif total != declared_total:
                raise ChUniverseError("SIX FQS totalRows drifted between pages")
            if payload.get("colNames") != list(columns):
                raise ChUniverseError("SIX FQS column contract changed")
            row_data = payload.get("rowData")
            if not isinstance(row_data, list):
                raise ChUniverseError("SIX FQS rowData is not a list")
            expected_rows = max(0, min(page_size, total - ((page - 1) * page_size)))
            if len(row_data) != expected_rows:
                raise ChUniverseError("SIX FQS page length does not match totalRows")
            for raw_row in row_data:
                if not isinstance(raw_row, list) or len(raw_row) != len(columns):
                    raise ChUniverseError("SIX FQS row shape changed")
                record = dict(zip(columns, raw_row))
                for field, expected_value in expected.items():
                    if str(record.get(field) or "") != expected_value:
                        raise ChUniverseError(
                            f"SIX FQS returned an unexpected {field} value"
                        )
                valor_id = str(record.get("ValorId") or "").strip()
                if not valor_id:
                    raise ChUniverseError("SIX FQS row has no ValorId")
                if valor_id in seen_ids:
                    raise ChUniverseError("SIX FQS repeated ValorId across pages")
                seen_ids.add(valor_id)
                records.append({**record, "retrieval_url": retrieval_url})
            total_pages = ceil(total / page_size) if total else 0
            if page == total_pages:
                break
            if page > total_pages:
                raise ChUniverseError("SIX FQS returned pages beyond totalRows")
        else:
            raise ChUniverseError(f"SIX FQS exceeded max_pages={max_pages}")
        if declared_total is None or len(records) != declared_total:
            raise ChUniverseError("SIX FQS result count did not reconcile")
        if delay_minutes is None or not source_millis:
            raise ChUniverseError("SIX FQS source timing is missing")
        return records, {
            "delay_minutes": delay_minutes,
            "from": _millis_iso(source_millis[0]),
            "to": _millis_iso(source_millis[-1]),
            "delayed_millis_from": source_millis[0],
            "delayed_millis_to": source_millis[-1],
        }

    def _get_json(self, url: str) -> Mapping[str, Any]:
        for attempt in range(self._max_retries + 1):
            self._wait()
            request = Request(
                url,
                headers={"User-Agent": self._user_agent, "Accept": "application/json"},
            )
            try:
                with self._opener(request, timeout=self._timeout) as response:
                    raw = response.read().decode("utf-8")
                payload = json.loads(raw)
                if not isinstance(payload, Mapping):
                    raise ChUniverseError("SIX FQS JSON root is not an object")
                return payload
            except HTTPError as error:
                if error.code not in RETRYABLE_HTTP_STATUS or attempt == self._max_retries:
                    raise ChUniverseError(
                        f"SIX FQS request failed with HTTP {error.code}"
                    ) from error
            except (URLError, TimeoutError) as error:
                if attempt == self._max_retries:
                    raise ChUniverseError("SIX FQS request failed after retries") from error
            except (UnicodeDecodeError, json.JSONDecodeError) as error:
                raise ChUniverseError("SIX FQS returned non-JSON content") from error
            self._sleeper(0.5 * (2**attempt))
        raise ChUniverseError("SIX FQS request failed")

    def _wait(self) -> None:
        with self._lock:
            now = self._clock()
            if self._last_request_at is not None:
                remaining = self._minimum_interval - (now - self._last_request_at)
                if remaining > 0:
                    self._sleeper(remaining)
                    now = self._clock()
            self._last_request_at = now


def load_ch_universe(path: Optional[Path] = None) -> Optional[Mapping[str, Any]]:
    """Load a validated cache payload, or ``None`` when absent/corrupt."""
    try:
        payload = json.loads(_cache_path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if (
        not isinstance(payload, Mapping)
        or not isinstance(payload.get("items"), list)
        or not payload.get("items")
    ):
        return None
    return payload


def refresh_ch_universe(
    *,
    path: Optional[Path] = None,
    client: Optional[SixFqsClient] = None,
    refreshed_at: Optional[str] = None,
    minimum_swiss_shares: int = 200,
    minimum_foreign_shares: int = 20,
    minimum_sponsored_foreign_shares: int = 250,
    minimum_etfs: int = 1000,
    page_size: int = DEFAULT_PAGE_SIZE,
    max_pages: int = DEFAULT_MAX_PAGES,
) -> Mapping[str, Any]:
    """Refresh SIX shares, sponsored foreign shares and ETFs atomically."""
    try:
        active_client = client or SixFqsClient.from_environment()
        scopes = active_client.fetch_all(
            page_size=page_size,
            max_pages=max_pages,
        )
    except ChUniverseError:
        raise
    except Exception as error:
        raise ChUniverseError(f"SIX universe refresh failed: {error}") from error
    expected_scopes = {
        "swiss_shares",
        "foreign_shares",
        "sponsored_foreign_shares",
        "etfs",
    }
    if set(scopes) != expected_scopes:
        raise ChUniverseError("SIX universe did not return all required scopes")
    source_timing = _aggregate_source_timing(
        getattr(active_client, "last_scope_metadata", None),
        expected_scopes,
    )
    counts = {scope: len(list(scopes[scope])) for scope in expected_scopes}
    if counts["swiss_shares"] < minimum_swiss_shares:
        raise ChUniverseError("SIX Swiss Shares scope is suspiciously small")
    if counts["foreign_shares"] < minimum_foreign_shares:
        raise ChUniverseError("SIX Foreign Shares scope is suspiciously small")
    if (
        counts["sponsored_foreign_shares"]
        < minimum_sponsored_foreign_shares
    ):
        raise ChUniverseError(
            "SIX Sponsored Foreign Shares scope is suspiciously small"
        )
    if counts["etfs"] < minimum_etfs:
        raise ChUniverseError("SIX ETF scope is suspiciously small")

    items: List[Mapping[str, Any]] = []
    seen_valor_ids: set[str] = set()
    for scope in (
        "swiss_shares",
        "foreign_shares",
        "sponsored_foreign_shares",
    ):
        for row in scopes[scope]:
            item = _share_item(row)
            _claim_valor_id(item, seen_valor_ids)
            items.append(item)
    for row in scopes["etfs"]:
        item = _etf_item(row)
        _claim_valor_id(item, seen_valor_ids)
        items.append(item)

    ticker_counts: Dict[str, int] = {}
    counts_by_type: Dict[str, int] = {}
    for item in items:
        ticker = str(item["ticker"])
        ticker_counts[ticker] = ticker_counts.get(ticker, 0) + 1
        instrument_type = str(item["instrument_type"])
        counts_by_type[instrument_type] = counts_by_type.get(instrument_type, 0) + 1
    ambiguous = sorted(key for key, count in ticker_counts.items() if count > 1)
    snapshot_at = refreshed_at or datetime.now(timezone.utc).isoformat()
    payload: Mapping[str, Any] = {
        "updated_at": snapshot_at,
        "source_effective_date": str(source_timing["to"])[:10],
        "source_effective_at": source_timing["to"],
        "source_effective_range": source_timing,
        "source": ["six_share_explorer", "six_etf_explorer"],
        "source_url": FQS_URL,
        "coverage": "official_partial_six_exchange_metadata",
        "coverage_boundary": {
            "included": [
                "SIX Swiss Shares (SA)",
                "SIX Foreign Shares (AA)",
                "SIX Sponsored Foreign Shares (SP) as foreign-primary trading lines",
                "SIX ETFs (ET/FU)",
                "SIX subscription rights retained as a separate non-equity type",
            ],
            "not_covered": [
                "routing-only Swiss MTF order books as separate issuer masters",
                "historical and delisted securities",
                "ETF issuer disclosures",
            ],
            "internal_metadata_cache_only": True,
        },
        "counts": {
            "total": len(items),
            **counts,
            "ambiguous_tickers": len(ambiguous),
        },
        "counts_by_type": counts_by_type,
        "excluded_counts": {
            "unknown_security_type": 0,
            "duplicate_valor_id": 0,
        },
        "ambiguous_tickers": ambiguous,
        "items": sorted(
            items,
            key=lambda item: (
                str(item["instrument_type"]),
                str(item["ticker"]),
                str(item["valor_id"]),
            ),
        ),
    }
    _atomic_write(_cache_path(path), payload)
    return payload


def ch_universe_name_map(
    path: Optional[Path] = None,
) -> Mapping[str, Mapping[str, str]]:
    """Return only unambiguous ticker/ISIN aliases from the SIX cache."""
    payload = load_ch_universe(path)
    if not payload:
        return {}
    candidates: Dict[str, List[Mapping[str, str]]] = {}
    for raw in payload.get("items") or []:
        if not isinstance(raw, Mapping):
            continue
        if str(raw.get("instrument_type") or "") == "subscription_right":
            # Rights are useful searchable metadata but are not issuer equity
            # identities and must not resolve a requested listed company.
            continue
        ticker = normalize_ch_ticker(str(raw.get("ticker") or ""))
        if not ticker:
            continue
        identity = {
            "name": str(raw.get("name") or ticker),
            "exchange": str(raw.get("exchange") or "SIX Swiss Exchange"),
            "board": str(raw.get("board") or "SIX Swiss Exchange"),
            "isin": str(raw.get("isin") or ""),
            "instrument_type": str(raw.get("instrument_type") or "equity"),
            "official_id": str(raw.get("valor_id") or ""),
        }
        for alias in (ticker, str(raw.get("isin") or "")):
            key = normalize_ch_ticker(alias)
            if key:
                candidates.setdefault(key, []).append(identity)
    resolved: Dict[str, Mapping[str, str]] = {}
    for key, identities in candidates.items():
        if len({identity["official_id"] for identity in identities}) == 1:
            resolved[key] = identities[0]
            continue
        # Sponsored shares commonly have CHF and USD trading lines with
        # distinct ValorIds but one issuer, symbol and ISIN.  Resolving that
        # issuer identity is safe; the trading-line ambiguity remains visible
        # in the cache and no currency-specific line is selected for trading.
        signatures = {
            (
                identity["name"],
                identity["isin"],
                identity["instrument_type"],
            )
            for identity in identities
        }
        if (
            len(signatures) == 1
            and identities[0]["instrument_type"] == "sponsored_foreign_share"
        ):
            resolved[key] = identities[0]
    return resolved


def search_ch_universe(
    query: str,
    path: Optional[Path] = None,
) -> List[Mapping[str, Any]]:
    payload = load_ch_universe(path)
    needle = str(query or "").strip().casefold()
    if not payload or not needle:
        return []
    matches: List[Mapping[str, Any]] = []
    for item in payload.get("items") or []:
        if not isinstance(item, Mapping):
            continue
        haystack = " ".join(
            str(item.get(field) or "")
            for field in (
                "ticker", "name", "isin", "board", "instrument_type", "valor_id"
            )
        ).casefold()
        if needle in haystack:
            matches.append(dict(item))
        if len(matches) >= 50:
            break
    return matches


def _share_item(row: Mapping[str, Any]) -> Mapping[str, Any]:
    name = str(row.get("ShortName") or "").strip()
    ticker = normalize_ch_ticker(str(row.get("ValorSymbol") or ""))
    isin = str(row.get("ISIN") or "").strip().upper()
    valor_id = str(row.get("ValorId") or "").strip()
    title_segment = str(row.get("TitleSegment") or "")
    listing_code = str(row.get("ListingSegmentCode") or "").strip()
    listing_desc = str(row.get("ListingSegmentDesc") or "").strip()
    security_type = str(row.get("SecTypeDesc") or "").strip()
    security_type_code = str(row.get("SecTypeCode") or "").strip().upper()
    if (
        not name
        or not ticker
        or not _ISIN.fullmatch(isin)
        or not valor_id
        or title_segment not in {"SA", "AA", "SP"}
        or str(row.get("PortalSegment") or "") != "EQ"
        or not listing_code
        or not listing_desc
        or not security_type
    ):
        raise ChUniverseError("SIX share row is missing required identity fields")
    try:
        instrument_type = _SHARE_INSTRUMENT_TYPES[security_type_code]
    except KeyError as error:
        raise ChUniverseError(
            f"SIX share row has unknown SecTypeCode {security_type_code!r}"
        ) from error
    trading_currency = str(row.get("TradingBaseCurrency") or "").strip().upper()
    first_trading_date = str(row.get("FirstTradingDate") or "").strip()
    if title_segment == "SP":
        if (
            security_type_code != "SS"
            or listing_code != "SP"
            or not re.fullmatch(r"[A-Z]{3}", trading_currency)
            or not re.fullmatch(r"\d{8}", first_trading_date)
        ):
            raise ChUniverseError(
                "SIX sponsored-share row is missing its official segment metadata"
            )
    elif security_type_code == "SS":
        raise ChUniverseError(
            "SIX Sponsored Foreign Share appeared outside TitleSegment=SP"
        )
    return {
        "ticker": ticker,
        "name": name,
        "isin": isin,
        "valor_id": valor_id,
        "valor_number": str(row.get("ValorNumber") or ""),
        "exchange": "SIX Swiss Exchange",
        "board": listing_desc,
        "listing_segment_code": listing_code,
        "title_segment": title_segment,
        "security_type_code": security_type_code,
        "security_type": security_type,
        "instrument_type": instrument_type,
        "trading_currency": trading_currency or None,
        "first_trading_date": first_trading_date or None,
        "primary_listing_outside_switzerland": title_segment == "SP",
        "source": (
            "six_sponsored_foreign_shares"
            if title_segment == "SP"
            else "six_share_explorer"
        ),
        "source_url": str(row.get("retrieval_url") or FQS_URL),
        "official_detail_url": (
            "https://www.six-group.com/en/market-data/shares/share-explorer/"
            f"share-details.{valor_id}.html"
        ),
    }


def _etf_item(row: Mapping[str, Any]) -> Mapping[str, Any]:
    name = str(row.get("FundLongName") or "").strip()
    ticker = normalize_ch_ticker(str(row.get("ValorSymbol") or ""))
    isin = str(row.get("ISIN") or "").strip().upper()
    valor_id = str(row.get("ValorId") or "").strip()
    trading_currency = str(row.get("TradingBaseCurrency") or "").strip().upper()
    if (
        not name
        or not ticker
        or not _ISIN.fullmatch(isin)
        or not valor_id
        or not trading_currency
        or str(row.get("ProductLine") or "") != "ET"
        or str(row.get("PortalSegment") or "") != "FU"
    ):
        raise ChUniverseError("SIX ETF row is missing required identity fields")
    return {
        "ticker": ticker,
        "name": name,
        "isin": isin,
        "valor_id": valor_id,
        "exchange": "SIX Swiss Exchange",
        "board": "SIX ETF",
        "instrument_type": "etf",
        "trading_currency": trading_currency,
        "fund_currency": str(row.get("FundCurrency") or "").upper(),
        "replication_method": str(row.get("ReplicationMethodDesc") or ""),
        "underlying_geography": str(row.get("UnderlyingGeographicalDesc") or ""),
        "legal_structure_country": str(
            row.get("LegalStructureCountryDesc") or ""
        ),
        "management_fee": row.get("ManagementFee"),
        "source": "six_etf_explorer",
        "source_url": str(row.get("retrieval_url") or FQS_URL),
        "official_detail_url": (
            "https://www.six-group.com/en/market-data/etf/etf-explorer/"
            f"etf-detail.{valor_id}.html"
        ),
    }


def _claim_valor_id(item: Mapping[str, Any], seen: set[str]) -> None:
    valor_id = str(item.get("valor_id") or "")
    if not valor_id or valor_id in seen:
        raise ChUniverseError("SIX universe contains a duplicate ValorId")
    seen.add(valor_id)


def _fqs_source_timing(payload: Mapping[str, Any]) -> Mapping[str, Any]:
    try:
        delay_minutes = int(payload["delayMinutes"])
        delayed_millis = int(payload["delayedMillis"])
        delayed_text = str(payload["delayedDateTime"])
        delayed_local = datetime.strptime(
            delayed_text,
            "%Y%m%dT%H:%M:%S.%f",
        ).replace(tzinfo=_SIX_TIME)
    except (KeyError, TypeError, ValueError) as error:
        raise ChUniverseError("SIX FQS source timing fields are invalid") from error
    if delay_minutes < 0 or delay_minutes > 24 * 60 or delayed_millis <= 0:
        raise ChUniverseError("SIX FQS source timing values are invalid")
    derived_millis = round(delayed_local.timestamp() * 1000)
    if abs(derived_millis - delayed_millis) > 1:
        raise ChUniverseError("SIX FQS delayedDateTime disagrees with delayedMillis")
    return {
        "delay_minutes": delay_minutes,
        "delayed_millis": delayed_millis,
    }


def _millis_iso(value: int) -> str:
    return datetime.fromtimestamp(value / 1000, timezone.utc).isoformat()


def _aggregate_source_timing(
    raw: Any,
    expected_scopes: set[str],
) -> Mapping[str, Any]:
    if not isinstance(raw, Mapping) or set(raw) != expected_scopes:
        raise ChUniverseError("SIX universe source timing is incomplete")
    normalized: Dict[str, Mapping[str, Any]] = {}
    starts: List[datetime] = []
    ends: List[datetime] = []
    for scope in sorted(expected_scopes):
        timing = raw.get(scope)
        if not isinstance(timing, Mapping):
            raise ChUniverseError("SIX universe source timing is invalid")
        try:
            start = datetime.fromisoformat(str(timing["from"]))
            end = datetime.fromisoformat(str(timing["to"]))
            delay_minutes = int(timing["delay_minutes"])
            millis_from = int(timing["delayed_millis_from"])
            millis_to = int(timing["delayed_millis_to"])
        except (KeyError, TypeError, ValueError) as error:
            raise ChUniverseError("SIX universe source timing is invalid") from error
        if (
            start.tzinfo is None
            or end.tzinfo is None
            or start > end
            or delay_minutes < 0
            or millis_from > millis_to
            or _millis_iso(millis_from) != start.isoformat()
            or _millis_iso(millis_to) != end.isoformat()
        ):
            raise ChUniverseError("SIX universe source timing is inconsistent")
        starts.append(start)
        ends.append(end)
        normalized[scope] = dict(timing)
    return {
        "from": min(starts).isoformat(),
        "to": max(ends).isoformat(),
        "scopes": normalized,
        "single_snapshot": len({*starts, *ends}) == 1,
    }


def _cache_path(path: Optional[Path]) -> Path:
    return Path(path or os.environ.get("CH_UNIVERSE_CACHE_PATH", DEFAULT_CACHE_PATH))


def _atomic_write(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    temporary.replace(path)


__all__ = [
    "ChUniverseError",
    "FQS_URL",
    "PHASE4_BOUNDARY",
    "SPONSORED_SHARE_COLUMNS",
    "SixFqsClient",
    "ch_universe_name_map",
    "load_ch_universe",
    "refresh_ch_universe",
    "search_ch_universe",
]
