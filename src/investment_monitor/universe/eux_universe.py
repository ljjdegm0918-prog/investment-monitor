"""Eurex (EUX) tradeable product universe cache (breadth only).

Source (live verified 2026-08-11): the key-free official Eurex product
list CSV linked from ``eurex.com/ex-en/markets/productSearch``:

``https://www.eurex.com/resource/blob/2281488/ee44f47447e255ee9de637f5ce0896e7/data/productlist.csv``

Semicolon-delimited; 2,997 product rows (product-level, not individual
expiry contracts). Columns include ``PRODUCT_ID`` (e.g. ``FDAX`` /
``FGBL`` / ``2FE``), ``PRODUCT_TYPE`` (FSTK/OSTK/FINX/OINX/FCUR/FBND/...),
``PRODUCT_NAME``, ``PRODUCT_GROUP`` (e.g. INDEX FUTURES, SINGLE STOCK
OPTIONS), ``CURRENCY``, ``PRODUCT_ISIN``, ``UNDERLYING_ISIN``,
``COUNTRY_CODE``, ``CASH_MARKET_ID``, ``SETTLEMENT_TYPE`` and
``EXERCISE_STYLE``. This is a derivatives product directory - no Xetra
cash equities/ETFs and no Cboe Europe symbols are mixed in, and no
hand-written FDAX-style seed is shipped. The blob URL may change (the
``productSearch`` page is the stable entry point), so an environment
override is provided.

The cache is breadth only and never flows into information_items / Today
feed. It backfills product name / ISIN / group on add-company.
"""

from __future__ import annotations

import csv
import io
import json
import logging
import os
import ssl
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Mapping, Optional
from urllib.request import HTTPSHandler, Request, build_opener, urlopen

from ..web_repository import normalize_eux_ticker

LOGGER = logging.getLogger(__name__)

DEFAULT_CACHE_PATH = ".cache/investment_monitor/eux_universe.json"
PRODUCT_URL = (
    "https://www.eurex.com/resource/blob/2281488/"
    "ee44f47447e255ee9de637f5ce0896e7/data/productlist.csv"
)
PRODUCT_URL_ENV = "EUX_UNIVERSE_PRODUCT_URL"
PRODUCT_PAGE_URL = "https://www.eurex.com/ex-en/markets/productSearch"
DEFAULT_USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/126.0 Safari/537.36"


class EuxUniverseError(RuntimeError):
    """Raised when the EUX universe cannot be refreshed at all."""


def load_eux_universe(
    path: Optional[Path] = None,
) -> Optional[Mapping[str, Any]]:
    """Load a cached EUX universe payload, or None when absent/invalid."""
    cache_path = _cache_path(path)
    try:
        with cache_path.open("r", encoding="utf-8") as cache_file:
            return json.load(cache_file)
    except (OSError, json.JSONDecodeError):
        return None


def refresh_eux_universe(
    *,
    path: Optional[Path] = None,
    opener: Optional[Callable[..., Any]] = None,
    product_url: Optional[str] = None,
    refreshed_at: Optional[str] = None,
) -> Mapping[str, Any]:
    """Refresh the EUX universe from the official Eurex product list CSV.

    The Eurex host shows intermittent TLS EOFs, so the fetch retries a few
    times before failing. The cache is written atomically (tmp + replace)
    and is breadth only (never information_items).
    """
    cache_path = _cache_path(path)
    verify_ssl = (
        os.environ.get("EUX_UNIVERSE_VERIFY_SSL", "true")
        .strip()
        .lower()
    ) not in {"0", "false", "no", "off"}
    default_opener = _make_opener(verify_ssl)
    url = product_url or os.environ.get(PRODUCT_URL_ENV, PRODUCT_URL)

    try:
        rows = _fetch_product_rows(url, opener or default_opener)
    except Exception as error:
        LOGGER.warning("eux_universe source=eurex_productlist_csv failed: %s", error)
        raise EuxUniverseError(
            f"Eurex product list CSV failed: {error}"
        ) from error

    entries: Dict[str, Mapping[str, Any]] = {}
    counts: Dict[str, int] = {}
    group_counts: Dict[str, int] = {}
    for row in rows:
        ticker = str(row.get("ticker") or "")
        if not ticker or ticker in entries:
            continue
        product_type = str(row.get("product_type") or "UNKNOWN").upper()
        group = str(row.get("group") or "Eurex")
        entries[ticker] = {
            "ticker": ticker,
            "name": str(row.get("name") or ticker),
            "product_type": product_type,
            "group": group,
            "currency": str(row.get("currency") or ""),
            "product_isin": str(row.get("product_isin") or ""),
            "underlying_isin": str(row.get("underlying_isin") or ""),
            "country": str(row.get("country") or ""),
            "cash_market_id": str(row.get("cash_market_id") or ""),
            "board": "Eurex",
            "exchange": "Eurex",
            "status": "active",
        }
        counts[product_type] = counts.get(product_type, 0) + 1
        group_counts[group] = group_counts.get(group, 0) + 1

    if not entries:
        raise EuxUniverseError(
            "Eurex product list returned no parseable product rows."
        )

    payload = {
        "updated_at": (
            refreshed_at or datetime.now(timezone.utc).isoformat()
        ),
        "source": ["eurex_productlist_csv"],
        "page_url": PRODUCT_PAGE_URL,
        "counts": dict(sorted(counts.items())),
        "counts_by_group": dict(
            sorted(group_counts.items(), key=lambda item: item[0])
        ),
        "items": sorted(
            entries.values(),
            key=lambda item: item["ticker"],
        ),
    }
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = cache_path.with_suffix(cache_path.suffix + ".tmp")
    with temporary_path.open("w", encoding="utf-8") as cache_file:
        json.dump(payload, cache_file, ensure_ascii=False)
    temporary_path.replace(cache_path)
    return payload


def eux_universe_name_map(
    path: Optional[Path] = None,
) -> Mapping[str, Mapping[str, str]]:
    """Return normalized product code -> name/exchange/board/isin."""
    payload = load_eux_universe(path)
    if not payload:
        return {}
    result: Dict[str, Mapping[str, str]] = {}
    for item in payload.get("items") or []:
        ticker = str(item.get("ticker") or "").strip()
        if not ticker:
            continue
        result[ticker] = {
            "name": str(item.get("name") or ticker),
            "exchange": str(item.get("exchange") or "Eurex"),
            "board": str(item.get("board") or "Eurex"),
            "isin": str(item.get("product_isin") or ""),
            "product_type": str(item.get("product_type") or ""),
            "group": str(item.get("group") or ""),
        }
    return result


def search_eux_universe(
    query: str,
    path: Optional[Path] = None,
) -> List[Mapping[str, Any]]:
    """Search the cached EUX universe by product code, name or group."""
    payload = load_eux_universe(path)
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
            f"{item.get('product_isin') or ''} "
            f"{item.get('group') or ''} "
            f"{item.get('product_type') or ''}"
        ).lower()
        if needle in haystack:
            matches.append(dict(item))
        if len(matches) >= 50:
            break
    return matches


def _fetch_product_rows(
    url: str,
    opener: Callable[..., Any],
) -> List[Mapping[str, Any]]:
    text = _get_csv(url, opener)
    reader = csv.reader(io.StringIO(text), delimiter=";")
    rows = list(reader)
    if not rows:
        raise EuxUniverseError("Eurex product list CSV is empty.")
    header = [str(cell).strip() for cell in rows[0]]
    if "PRODUCT_ID" not in header:
        raise EuxUniverseError(
            "Eurex product list CSV has no PRODUCT_ID header (shape changed?)."
        )
    index = {name: i for i, name in enumerate(header)}

    def value(row: List[str], name: str) -> str:
        i = index.get(name)
        if i is None or i >= len(row):
            return ""
        return str(row[i]).strip()

    records: List[Mapping[str, Any]] = []
    for row in rows[1:]:
        product_id = value(row, "PRODUCT_ID")
        if not product_id:
            continue
        ticker = normalize_eux_ticker(product_id)
        if not ticker:
            continue
        records.append(
            {
                "ticker": ticker,
                "name": value(row, "PRODUCT_NAME") or ticker,
                "product_type": value(row, "PRODUCT_TYPE"),
                "group": value(row, "PRODUCT_GROUP") or "Eurex",
                "currency": value(row, "CURRENCY"),
                "product_isin": value(row, "PRODUCT_ISIN"),
                "underlying_isin": value(row, "UNDERLYING_ISIN"),
                "country": value(row, "COUNTRY_CODE"),
                "cash_market_id": value(row, "CASH_MARKET_ID"),
            }
        )
    if not records:
        raise EuxUniverseError(
            "Eurex product list CSV returned no parseable product rows."
        )
    return records


def _get_csv(url: str, opener: Callable[..., Any]) -> str:
    last_error: Optional[Exception] = None
    for attempt in range(3):
        try:
            request = Request(
                url,
                headers={
                    "User-Agent": DEFAULT_USER_AGENT,
                    "Accept": "text/csv,*/*",
                    "Accept-Language": "en-GB,de;q=0.8",
                },
                method="GET",
            )
            with opener(request, timeout=90) as response:
                raw = response.read()
            return raw.decode("utf-8-sig", errors="replace")
        except Exception as error:
            last_error = error
            LOGGER.warning(
                "eux_universe fetch attempt=%d failed: %s",
                attempt + 1,
                error,
            )
            time.sleep(1.5 * (attempt + 1))
    raise EuxUniverseError(str(last_error))


def _make_opener(verify_ssl: bool) -> Callable[..., Any]:
    if verify_ssl:
        return urlopen
    return build_opener(
        HTTPSHandler(context=ssl._create_unverified_context())
    ).open


def _cache_path(path: Optional[Path]) -> Path:
    return Path(
        path or os.environ.get("EUX_UNIVERSE_CACHE_PATH", DEFAULT_CACHE_PATH)
    )
