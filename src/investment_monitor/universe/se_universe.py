"""Official partial Swedish equity universe from Nasdaq Nordic's screener.

The public Nasdaq endpoint is queried separately for ``MAIN_MARKET`` and
``FIRST_NORTH`` with ``market=STO``; every returned row must declare
``assetClass=SHARES``.  That provides
an official directory for Nasdaq Stockholm's two named boards, but is not a
national Swedish security master: NGM, Spotlight, historical/delisted issues
and other venues remain outside this cache.  The explicit boundary is stored
with every refresh so downstream callers cannot mistake it for complete SE
coverage.
"""

from __future__ import annotations

import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional

from ..sources.nasdaq_se.client import NasdaqSeClient
from ..web_repository import normalize_se_ticker

DEFAULT_CACHE_PATH = ".cache/investment_monitor/se_universe.json"
MIN_MAIN_MARKET_ITEMS = 150
MIN_FIRST_NORTH_ITEMS = 40
_ISIN = re.compile(r"[A-Z]{2}[A-Z0-9]{10}")
_BOARD_NAMES = {
    "MAIN_MARKET": "Nasdaq Stockholm Main Market",
    "FIRST_NORTH": "Nasdaq First North Growth Market Sweden",
}

# The old stub boundary is retained as a historical audit note, but live data
# now comes from the documented Nasdaq Nordic Shares Screener route.
PHASE4_BOUNDARY = {
    "universe": "partial",
    "disclosure": "live",
    "evidence": (
        "api.nasdaq.com/api/nordic/screener/shares with market=STO, "
        "category=MAIN_MARKET/FIRST_NORTH; returned assetClass=SHARES"
    ),
}


class SeUniverseError(RuntimeError):
    """Raised when the official SE directory cannot be validated safely."""


def _cache_path(path: Optional[Path]) -> Path:
    return Path(path or os.environ.get("SE_UNIVERSE_CACHE_PATH", DEFAULT_CACHE_PATH))


def load_se_universe(path: Optional[Path] = None) -> Optional[Mapping[str, Any]]:
    """Load a cached universe payload, returning ``None`` for absent/bad JSON."""
    cache_path = _cache_path(path)
    try:
        with cache_path.open("r", encoding="utf-8") as cache_file:
            payload = json.load(cache_file)
    except (OSError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, Mapping) else None


def refresh_se_universe(
    *,
    path: Optional[Path] = None,
    client: Optional[NasdaqSeClient] = None,
    refreshed_at: Optional[str] = None,
    minimum_main_market_items: int = MIN_MAIN_MARKET_ITEMS,
    minimum_first_north_items: int = MIN_FIRST_NORTH_ITEMS,
) -> Mapping[str, Any]:
    """Refresh Nasdaq Stockholm Main Market and First North atomically.

    The client validates API status and all pagination before this function
    receives rows.  We repeat the classification, identity, and breadth
    checks here because this cache is also called with test/specialized
    clients.  Any failure happens before the temporary cache is replaced,
    preserving the previous good snapshot.
    """
    if minimum_main_market_items <= 0 or minimum_first_north_items <= 0:
        raise ValueError("SE universe minimum category sizes must be positive")
    try:
        rows = (client or NasdaqSeClient.from_environment()).fetch_share_directory(
            market="STO"
        )
    except Exception as error:
        raise SeUniverseError(f"Nasdaq Stockholm directory failed: {error}") from error
    if not isinstance(rows, list):
        raise SeUniverseError("Nasdaq Stockholm directory rows are not a list")

    entries: List[Mapping[str, Any]] = []
    category_counts = {category: 0 for category in _BOARD_NAMES}
    seen_tickers: Dict[str, str] = {}
    seen_isins: Dict[str, str] = {}
    for row in rows:
        if not isinstance(row, Mapping):
            raise SeUniverseError("Nasdaq Stockholm directory row is not an object")
        category = str(row.get("listing_category") or "")
        if category not in _BOARD_NAMES:
            raise SeUniverseError("Nasdaq Stockholm directory has an unknown category")
        if str(row.get("listing_market") or "").upper() != "STO":
            raise SeUniverseError("Nasdaq Stockholm directory did not retain market=STO")
        if str(row.get("assetClass") or "").upper() != "SHARES":
            raise SeUniverseError("Nasdaq Stockholm directory included a non-share asset")
        symbol = str(row.get("symbol") or "").strip()
        ticker = _canonical_ticker(symbol)
        isin = str(row.get("isin") or "").strip().upper()
        name = str(row.get("fullName") or "").strip()
        orderbook_id = str(row.get("orderbookId") or "").strip()
        if not ticker or not _ISIN.fullmatch(isin) or not name or not orderbook_id:
            raise SeUniverseError("Nasdaq Stockholm directory row is missing identity fields")
        prior_isin = seen_tickers.get(ticker)
        if prior_isin is not None:
            raise SeUniverseError(
                f"Nasdaq Stockholm directory repeated ticker {ticker}"
                + (f" with different ISIN {isin}" if prior_isin != isin else "")
            )
        prior_ticker = seen_isins.get(isin)
        if prior_ticker is not None:
            raise SeUniverseError(
                f"Nasdaq Stockholm directory repeated ISIN {isin}"
                + (f" for ticker {ticker}" if prior_ticker != ticker else "")
            )
        seen_tickers[ticker] = isin
        seen_isins[isin] = ticker
        board = _BOARD_NAMES[category]
        category_counts[category] += 1
        entries.append(
            {
                "ticker": ticker,
                "symbol": symbol,
                "aliases": _aliases_for(symbol, ticker),
                "isin": isin,
                "name": name,
                "exchange": "Nasdaq Stockholm",
                "board": board,
                "listing_category": category,
                "currency": str(row.get("currency") or "").upper(),
                "asset_class": "SHARES",
                "orderbook_id": orderbook_id,
                "source": "nasdaq_nordic_shares_screener",
                "source_url": str(row.get("retrieval_url") or ""),
            }
        )
    if category_counts["MAIN_MARKET"] < minimum_main_market_items:
        raise SeUniverseError(
            "Nasdaq Stockholm Main Market is suspiciously small: "
            f"{category_counts['MAIN_MARKET']} < {minimum_main_market_items}"
        )
    if category_counts["FIRST_NORTH"] < minimum_first_north_items:
        raise SeUniverseError(
            "Nasdaq First North is suspiciously small: "
            f"{category_counts['FIRST_NORTH']} < {minimum_first_north_items}"
        )

    payload: Mapping[str, Any] = {
        "updated_at": refreshed_at or datetime.now(timezone.utc).isoformat(),
        "source": ["nasdaq_nordic_shares_screener"],
        "coverage": "official_partial_nasdaq_stockholm_main_market_and_first_north",
        "coverage_boundary": {
            "included": [
                "Nasdaq Stockholm Main Market shares",
                "Nasdaq First North Growth Market Sweden shares",
            ],
            "official_request": {
                "market": "STO",
                "categories": ["MAIN_MARKET", "FIRST_NORTH"],
            },
            "response_constraints": {"assetClass": "SHARES"},
            "not_covered": [
                "NGM",
                "Spotlight Stock Market",
                "other Swedish venues",
                "delisted and historical securities",
            ],
            "currency_is_audit_field_not_a_filter": True,
        },
        "counts": {
            "total": len(entries),
            "main_market": category_counts["MAIN_MARKET"],
            "first_north": category_counts["FIRST_NORTH"],
            "excluded_non_share_rows": 0,
            "excluded_other_markets": 0,
        },
        "items": sorted(entries, key=lambda item: (str(item["ticker"]), str(item["isin"]))),
    }
    cache_path = _cache_path(path)
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = cache_path.with_suffix(cache_path.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8") as cache_file:
        json.dump(payload, cache_file, ensure_ascii=False)
    temporary.replace(cache_path)
    return payload


def se_universe_name_map(path: Optional[Path] = None) -> Mapping[str, Mapping[str, str]]:
    """Return normalized ticker/ISIN aliases mapped to official identities."""
    payload = load_se_universe(path)
    if not payload:
        return {}
    result: Dict[str, Mapping[str, str]] = {}
    for item in payload.get("items") or []:
        if not isinstance(item, Mapping):
            continue
        ticker = normalize_se_ticker(str(item.get("ticker") or ""))
        if not ticker:
            continue
        board = str(item.get("board") or "Nasdaq Stockholm")
        identity = {
            "name": str(item.get("name") or ticker),
            "exchange": str(item.get("exchange") or "Nasdaq Stockholm"),
            "board": board,
            "isin": str(item.get("isin") or ""),
        }
        for value in (ticker, str(item.get("isin") or ""), *(item.get("aliases") or [])):
            key = normalize_se_ticker(str(value))
            if key and key not in result:
                result[key] = identity
    return result


def search_se_universe(query: str, path: Optional[Path] = None) -> List[Mapping[str, Any]]:
    """Search the cached official Nasdaq partial universe."""
    payload = load_se_universe(path)
    if not payload:
        return []
    needle = str(query or "").strip().casefold()
    if not needle:
        return []
    matches: List[Mapping[str, Any]] = []
    for item in payload.get("items") or []:
        if not isinstance(item, Mapping):
            continue
        haystack = " ".join(
            str(value or "")
            for value in (
                item.get("ticker"), item.get("symbol"), item.get("name"),
                item.get("isin"), item.get("board"),
                " ".join(str(alias) for alias in item.get("aliases") or []),
            )
        ).casefold()
        if needle in haystack:
            matches.append(dict(item))
        if len(matches) >= 50:
            break
    return matches


def _aliases_for(symbol: str, ticker: str) -> List[str]:
    """Keep source spelling and common Stockholm suffix without ambiguity."""
    aliases = [symbol.strip().upper(), f"{ticker}.ST"]
    return list(dict.fromkeys(alias for alias in aliases if alias and alias != ticker))


def _canonical_ticker(value: str) -> str:
    """Normalize Nasdaq's spaced share-class spelling to the project form.

    Nasdaq frequently returns ``ERIC B`` while project inputs conventionally
    use ``ERIC-B``.  Only a final one-letter class is rewritten; other spaces
    remain untouched so a mnemonic is not guessed into a different security.
    """
    normalized = normalize_se_ticker(value)
    match = re.fullmatch(r"(.+?)\s+([A-Z])", normalized)
    return f"{match.group(1)}-{match.group(2)}" if match else normalized


__all__ = [
    "MIN_FIRST_NORTH_ITEMS",
    "MIN_MAIN_MARKET_ITEMS",
    "PHASE4_BOUNDARY",
    "SeUniverseError",
    "load_se_universe",
    "refresh_se_universe",
    "search_se_universe",
    "se_universe_name_map",
]
