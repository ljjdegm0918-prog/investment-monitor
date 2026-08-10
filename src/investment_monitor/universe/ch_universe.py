"""CH tradeable universe cache (breadth only) - boundary stub.

CH-2 spike (2026-08-10) found no stable key-free official directory for
SIX Swiss Exchange equities:

* ``six-group.com/en/market-data/shares/*`` pages are React SPAs; the
  share-explorer detail pages expose only name/ticker/ISIN in meta tags
  (no board), so a full directory would need hundreds of page fetches
  without Main Standard / Sparks segmentation.
* ``api.six-group.com`` / ``webapp.api.six-group.com`` return JSON 404 for
  every public route tried; SIX market-data APIs are paid products.
* The SIX official-notices component (ser-ag.com) is also JS-driven with
  no public JSON list; SIX equity-issuer news is the paid Exfeed product.
* A hand-written SMI/SPI list would be exactly the forbidden "SMI seed
  pretending to be the full universe", so none is shipped.

The cache shape is still provided: ``load_ch_universe`` /
``ch_universe_name_map`` / ``search_ch_universe`` read a locally cached
JSON payload if one ever exists, and ``refresh_ch_universe`` raises
``ChUniverseError`` instead of faking a refresh. The cache is breadth only
and never flows into information_items.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, List, Mapping, Optional

DEFAULT_CACHE_PATH = ".cache/investment_monitor/ch_universe.json"


class ChUniverseError(RuntimeError):
    """Raised when the CH universe cannot be refreshed at all."""


def load_ch_universe(
    path: Optional[Path] = None,
) -> Optional[Mapping[str, Any]]:
    """Load a cached CH universe payload, or None when absent/invalid."""
    cache_path = _cache_path(path)
    try:
        with cache_path.open("r", encoding="utf-8") as cache_file:
            return json.load(cache_file)
    except (OSError, json.JSONDecodeError):
        return None


def refresh_ch_universe(
    *,
    path: Optional[Path] = None,
    opener=None,
    refreshed_at: Optional[str] = None,
) -> Mapping[str, Any]:
    """Refresh the CH universe.

    No free SIX directory source is wired (CH-2 spike B2), so this always
    raises ``ChUniverseError`` with the spike evidence instead of producing
    a fake or SMI-only universe. The cache shape is reserved for a future
    slice that lands a real SIX/regulator directory.
    """
    raise ChUniverseError(
        "CH universe refresh is not wired: CH-2 spike found no stable "
        "key-free SIX securities directory (React SPA pages, undocumented "
        "api.six-group.com routes, paid market-data/Exfeed products). See "
        "README Switzerland section."
    )


def ch_universe_name_map(
    path: Optional[Path] = None,
) -> Mapping[str, Mapping[str, str]]:
    """Return normalized ticker -> {name, exchange, board, isin}."""
    payload = load_ch_universe(path)
    if not payload:
        return {}
    result: dict = {}
    for item in payload.get("items") or []:
        ticker = str(item.get("ticker") or "").strip()
        if not ticker:
            continue
        board = str(
            item.get("board")
            or item.get("exchange")
            or "SIX Main Standard"
        )
        result[ticker] = {
            "name": str(item.get("name") or ticker),
            "exchange": board,
            "board": board,
            "isin": str(item.get("isin") or ""),
        }
    return result


def search_ch_universe(
    query: str,
    path: Optional[Path] = None,
) -> List[Mapping[str, Any]]:
    """Search the cached CH universe by ticker, name, ISIN or board."""
    payload = load_ch_universe(path)
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
            f"{item.get('isin') or ''} "
            f"{item.get('board') or ''}"
        ).lower()
        if needle in haystack:
            matches.append(dict(item))
        if len(matches) >= 50:
            break
    return matches


def _cache_path(path: Optional[Path]) -> Path:
    return Path(
        path or os.environ.get("CH_UNIVERSE_CACHE_PATH", DEFAULT_CACHE_PATH)
    )
