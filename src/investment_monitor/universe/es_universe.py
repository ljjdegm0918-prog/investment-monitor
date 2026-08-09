"""ES tradeable universe cache (breadth only) from the BME equity API.

Source (live verified 2026-08-10): the key-free official BME API used by
``bolsasymercados.es`` listed-companies pages
(``https://apiweb.bolsasymercados.es/Market/v1/EQ/ListedCompanies``).
Trading systems ``SIBE`` (main continuous market, ~123), ``Floor`` (~5)
and ``Latibex`` (~14) are kept in full; the ``MTF`` response is filtered to
the equity segments ``BMEGrowth`` (~111) and ``BMEScaleUp`` (~52) and
excludes funds (``SICAV``/``HedgeFunds``/``VCC``), ETF and non-equity rows.
The bulk response has ISIN/name but no ticker mnemonic, so tickers are
enriched per ISIN from ``v1/EQ/ShareDetailsInfo`` (rate-limited; cached
tickers are reused on later refreshes, and an entry whose enrichment fails
is stored without a ticker and retried next refresh). This is NOT the
Euronext CSV family used by FR/NL/IT: BME is a SIX company, not Euronext,
and no Madrid segment exists in the Euronext CSV.

The cache is breadth only and never flows into information_items / Today
feed. Each entry stores ticker/name/ISIN/board under the normalized ES
ticker so the ES-1 CNMV connector can align by name/ISIN once the cache is
refreshed.
"""

from __future__ import annotations

import json
import logging
import os
import ssl
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Mapping, Optional
from urllib.parse import quote
from urllib.request import HTTPSHandler, Request, build_opener, urlopen

LOGGER = logging.getLogger(__name__)

DEFAULT_CACHE_PATH = ".cache/investment_monitor/es_universe.json"
DIRECTORY_URL = (
    "https://apiweb.bolsasymercados.es/Market/v1/EQ/ListedCompanies"
)
DETAIL_URL = (
    "https://apiweb.bolsasymercados.es/Market/v1/EQ/ShareDetailsInfo"
)
DIRECTORY_URL_ENV = "ES_UNIVERSE_DIRECTORY_URL"
DETAIL_URL_ENV = "ES_UNIVERSE_DETAIL_URL"
DEFAULT_USER_AGENT = "InvestmentMonitor/0.1 (internal workspace)"

_MAIN_TRADING_SYSTEMS = ("SIBE", "Floor", "Latibex")
_MTF_EQUITY_SEGMENTS = ("BMEGrowth", "BMEScaleUp")
_BOARD_LABELS = {
    "SIBE": "BME (SIBE)",
    "Floor": "BME (Floor)",
    "Latibex": "BME (Latibex)",
    "BMEGrowth": "BME Growth",
    "BMEScaleUp": "BME ScaleUp",
}


class EsUniverseError(RuntimeError):
    """Raised when the ES universe cannot be refreshed at all."""


def load_es_universe(
    path: Optional[Path] = None,
) -> Optional[Mapping[str, Any]]:
    """Load the cached universe payload, or None when absent/invalid."""
    cache_path = _cache_path(path)
    try:
        with cache_path.open("r", encoding="utf-8") as cache_file:
            return json.load(cache_file)
    except (OSError, json.JSONDecodeError):
        return None


def refresh_es_universe(
    *,
    path: Optional[Path] = None,
    opener: Optional[Callable[..., Any]] = None,
    directory_url: Optional[str] = None,
    detail_url: Optional[str] = None,
    refreshed_at: Optional[str] = None,
    requests_per_second: Optional[float] = None,
) -> Mapping[str, Any]:
    """Refresh the ES universe from the BME equity API.

    Main boards (SIBE/Floor/Latibex) and MTF equity segments
    (BMEGrowth/BMEScaleUp) are fetched; funds and other non-equity MTF rows
    are dropped. One board family failing (network/HTTP/JSON) is logged and
    does not discard the other family; only when every source fails is
    ``EsUniverseError`` raised. Tickers come from ``ShareDetailsInfo`` per
    ISIN, reusing tickers already present in the cache; set
    ``ES_UNIVERSE_ENRICH_TICKERS=false`` to skip enrichment (entries then
    stay in the payload without a ticker and are excluded from the name
    map). The cache is written atomically (tmp + replace).
    """
    cache_path = _cache_path(path)
    verify_ssl = (
        os.environ.get("ES_UNIVERSE_VERIFY_SSL", "true")
        .strip()
        .lower()
    ) not in {"0", "false", "no", "off"}
    default_opener = _make_opener(verify_ssl)
    active_opener = opener or default_opener
    directory = directory_url or os.environ.get(
        DIRECTORY_URL_ENV, DIRECTORY_URL
    )
    detail = detail_url or os.environ.get(DETAIL_URL_ENV, DETAIL_URL)
    enrich_tickers = (
        os.environ.get("ES_UNIVERSE_ENRICH_TICKERS", "true")
        .strip()
        .lower()
    ) not in {"0", "false", "no", "off"}
    rate = requests_per_second
    if rate is None:
        try:
            rate = float(
                os.environ.get("ES_UNIVERSE_REQUESTS_PER_SECOND", "1.0")
            )
        except ValueError as error:
            raise ValueError(
                "ES_UNIVERSE_REQUESTS_PER_SECOND must be a number."
            ) from error
    limiter = _RateLimiter(max(rate, 0.01))

    cached = load_es_universe(cache_path) or {}
    cached_tickers = {
        str(item.get("isin") or ""): str(item.get("ticker") or "")
        for item in cached.get("items") or []
        if item.get("isin") and item.get("ticker")
    }

    rows: List[Mapping[str, Any]] = []
    source_failures: List[str] = []
    for label, query in (
        ("bme_main", _main_query()),
        ("bme_mtf", _mtf_query()),
    ):
        try:
            payload = _get_json(f"{directory}?{query}", active_opener)
            rows.extend(_rows_from_payload(payload))
        except Exception as error:
            message = str(error) or error.__class__.__name__
            source_failures.append(f"{label}: {message}")
            LOGGER.warning(
                "es_universe source=%s failed: %s",
                label,
                error,
            )

    entries: Dict[str, Mapping[str, Any]] = {}
    counts: Dict[str, int] = {}
    for row in rows:
        isin = str(row.get("isin") or "").strip()
        if not isin or isin in entries:
            continue
        board = str(row.get("board") or "")
        ticker = str(cached_tickers.get(isin) or "")
        if enrich_tickers and not ticker:
            try:
                ticker = _fetch_ticker(
                    detail,
                    isin,
                    active_opener,
                    limiter,
                )
            except Exception as error:
                LOGGER.warning(
                    "es_universe ticker_enrich isin=%s failed: %s",
                    isin,
                    error,
                )
        entries[isin] = {
            "ticker": ticker,
            "name": str(row.get("name") or row.get("shareName") or ""),
            "share_name": str(row.get("shareName") or ""),
            "isin": isin,
            "board": board,
            "exchange": board,
            "company_key": str(row.get("company_key") or ""),
            "country": str(row.get("country") or ""),
            "status": "active",
        }
        counts[board] = counts.get(board, 0) + 1

    if not entries:
        raise EsUniverseError(
            "ES universe sources failed; no equity entries available."
        )

    payload = {
        "updated_at": (
            refreshed_at or datetime.now(timezone.utc).isoformat()
        ),
        "source": ["bme_equity_api"],
        "counts": counts,
        "items": sorted(
            entries.values(),
            key=lambda item: (
                item["ticker"] or item["isin"],
                item["isin"],
            ),
        ),
    }
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = cache_path.with_suffix(cache_path.suffix + ".tmp")
    with temporary_path.open("w", encoding="utf-8") as cache_file:
        json.dump(payload, cache_file, ensure_ascii=False)
    temporary_path.replace(cache_path)
    return payload


def es_universe_name_map(
    path: Optional[Path] = None,
) -> Mapping[str, Mapping[str, str]]:
    """Return normalized ticker -> {name, exchange, board, isin}."""
    payload = load_es_universe(path)
    if not payload:
        return {}
    result: Dict[str, Mapping[str, str]] = {}
    for item in payload.get("items") or []:
        ticker = str(item.get("ticker") or "").strip()
        if not ticker:
            continue
        board = str(
            item.get("board")
            or item.get("exchange")
            or "BME (SIBE)"
        )
        result[ticker] = {
            "name": str(
                item.get("share_name")
                or item.get("name")
                or ticker
            ),
            "exchange": board,
            "board": board,
            "isin": str(item.get("isin") or ""),
        }
    return result


def search_es_universe(
    query: str,
    path: Optional[Path] = None,
) -> List[Mapping[str, Any]]:
    """Search the cached ES universe by ticker, name, ISIN or board."""
    payload = load_es_universe(path)
    if not payload:
        return []
    needle = str(query or "").strip().lower()
    if not needle:
        return []
    matches: List[Mapping[str, Any]] = []
    for item in payload.get("items") or []:
        haystack = (
            f"{item.get('ticker') or ''} "
            f"{item.get('name') or ''} "
            f"{item.get('share_name') or ''} "
            f"{item.get('isin') or ''} "
            f"{item.get('board') or ''}"
        ).lower()
        if needle in haystack:
            matches.append(dict(item))
        if len(matches) >= 50:
            break
    return matches


def _rows_from_payload(payload: Any) -> List[Mapping[str, Any]]:
    if not isinstance(payload, Mapping):
        raise EsUniverseError("BME equity API returned a non-object payload.")
    data = payload.get("data")
    if not isinstance(data, list):
        raise EsUniverseError("BME equity API returned no data list.")
    rows: List[Mapping[str, Any]] = []
    for raw in data:
        if not isinstance(raw, Mapping):
            continue
        trading_system = str(raw.get("tradingSystem") or "").strip()
        mtf_segment = str(raw.get("mtfSegment") or "").strip()
        board = ""
        if trading_system in _MAIN_TRADING_SYSTEMS:
            board = _BOARD_LABELS.get(trading_system, trading_system)
        elif (
            trading_system == "MTF"
            and mtf_segment in _MTF_EQUITY_SEGMENTS
        ):
            board = _BOARD_LABELS.get(mtf_segment, mtf_segment)
        if not board:
            continue
        rows.append(
            {
                "isin": str(raw.get("isin") or "").strip(),
                "name": str(raw.get("name") or "").strip(),
                "shareName": str(raw.get("shareName") or "").strip(),
                "company_key": str(raw.get("companyKey") or "").strip(),
                "country": str(raw.get("country") or "").strip(),
                "board": board,
            }
        )
    return rows


def _main_query() -> str:
    return (
        f"tradingSystem={quote('SIBE,Floor,Latibex')}"
        "&page=0&pageSize=0"
    )


def _mtf_query() -> str:
    return "tradingSystem=MTF&page=0&pageSize=0"


def _fetch_ticker(
    detail_url: str,
    isin: str,
    opener: Callable[..., Any],
    limiter: "_RateLimiter",
) -> str:
    limiter.wait()
    payload = _get_json(
        f"{detail_url}?isin={quote(isin)}",
        opener,
    )
    if not isinstance(payload, Mapping):
        return ""
    return str(payload.get("ticker") or "").strip().upper()


def _get_json(url: str, opener: Callable[..., Any]) -> Any:
    request = Request(
        url,
        headers={
            "User-Agent": DEFAULT_USER_AGENT,
            "Accept": "application/json",
            "Accept-Language": "es,en;q=0.8",
        },
        method="GET",
    )
    with opener(request, timeout=60) as response:
        raw = response.read()
    try:
        return json.loads(raw.decode("utf-8", errors="replace"))
    except json.JSONDecodeError as error:
        raise EsUniverseError(
            "BME equity API returned non-JSON payload."
        ) from error


class _RateLimiter:
    """Minimal thread-safe rate limiter shared by ticker enrichment calls."""

    def __init__(self, requests_per_second: float) -> None:
        self._minimum_interval = 1.0 / requests_per_second
        self._lock = threading.Lock()
        self._last_request_at: Optional[float] = None

    def wait(self) -> None:
        with self._lock:
            now = time.monotonic()
            if self._last_request_at is not None:
                remaining = self._minimum_interval - (
                    now - self._last_request_at
                )
                if remaining > 0:
                    time.sleep(remaining)
            self._last_request_at = time.monotonic()


def _make_opener(verify_ssl: bool) -> Callable[..., Any]:
    if verify_ssl:
        return urlopen
    return build_opener(
        HTTPSHandler(context=ssl._create_unverified_context())
    ).open


def _cache_path(path: Optional[Path]) -> Path:
    return Path(
        path or os.environ.get("ES_UNIVERSE_CACHE_PATH", DEFAULT_CACHE_PATH)
    )
