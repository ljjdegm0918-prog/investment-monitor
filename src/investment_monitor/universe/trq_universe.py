"""Turquoise (TRQ) tradeable universe cache (breadth only).

TRQ-2 re-spike (2026-08-11) found **no stable key-free Turquoise
directory**:

* ``turquoise.com`` - parked domain for sale (HTTP 200, not the MTF).
* ``turquoise.eu`` - hosts an unrelated "Climate Tech Investment &
  Advisory" firm (HTTP 200 since 2026-08-11; was Cloudflare 403 on
  2026-08-10), not the LSEG MTF.
* ``tradeturquoise.com`` and the LSEG Turquoise paths redirect to
  ``londonstockexchange.com/securities-trading/turquoise``, a JS-only SPA
  shell with no server-rendered instrument data and no discoverable
  public JSON route.
* The historical LSEG reference files
  (``lseg.com/turquoise/symbol/YYYYMMDD_TRQX_Instrument.csv`` /
  ``..._TQEX_Instrument.csv``) return HTTP 404 (retired).

The cache shape is still provided: ``load_trq_universe`` /
``trq_universe_name_map`` / ``search_trq_universe`` read a locally cached
JSON payload if one ever exists (e.g. a future LSEG/Turquoise directory
slice), and ``refresh_trq_universe`` raises ``TrqUniverseError`` instead
of faking a refresh or reusing the Cboe Europe (CXE) CSV as a Turquoise
directory. The cache is breadth only and never flows into
information_items.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, List, Mapping, Optional

DEFAULT_CACHE_PATH = ".cache/investment_monitor/trq_universe.json"


class TrqUniverseError(RuntimeError):
    """Raised when the TRQ universe cannot be refreshed at all."""


def load_trq_universe(
    path: Optional[Path] = None,
) -> Optional[Mapping[str, Any]]:
    """Load a cached TRQ universe payload, or None when absent/invalid."""
    cache_path = _cache_path(path)
    try:
        with cache_path.open("r", encoding="utf-8") as cache_file:
            return json.load(cache_file)
    except (OSError, json.JSONDecodeError):
        return None


def refresh_trq_universe(
    *,
    path: Optional[Path] = None,
    opener=None,
    refreshed_at: Optional[str] = None,
) -> Mapping[str, Any]:
    """Refresh the TRQ universe.

    No free key-free Turquoise directory source is wired (TRQ-2 re-spike
    B2), so this always raises ``TrqUniverseError`` with the spike
    evidence instead of producing a fake or hand-written universe. The
    cache shape is reserved for a future slice that lands a real
    LSEG/Turquoise directory.
    """
    raise TrqUniverseError(
        "TRQ universe refresh is not wired: TRQ-2 re-spike (2026-08-11) "
        "found no stable key-free Turquoise directory (turquoise.com is a "
        "parked domain; turquoise.eu is an unrelated company; "
        "tradeturquoise.com redirects to a JS-only LSE SPA; the old LSEG "
        "TRQX/TQEX reference-file CSVs return 404). See README Turquoise "
        "section."
    )


def trq_universe_name_map(
    path: Optional[Path] = None,
) -> Mapping[str, Mapping[str, str]]:
    """Return normalized ticker -> {name, exchange, board, isin}."""
    payload = load_trq_universe(path)
    if not payload:
        return {}
    result: dict = {}
    for item in payload.get("items") or []:
        ticker = str(item.get("ticker") or "").strip()
        if not ticker:
            continue
        result[ticker] = {
            "name": str(item.get("name") or ticker),
            "exchange": str(item.get("exchange") or "Turquoise"),
            "board": str(item.get("board") or "TRQX/TQEX"),
            "isin": str(item.get("isin") or ""),
        }
    return result


def search_trq_universe(
    query: str,
    path: Optional[Path] = None,
) -> List[Mapping[str, Any]]:
    """Search the cached TRQ universe by ticker, name or ISIN."""
    payload = load_trq_universe(path)
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
            f"{item.get('isin') or ''}"
        ).lower()
        if needle in haystack:
            matches.append(dict(item))
        if len(matches) >= 50:
            break
    return matches


def _cache_path(path: Optional[Path]) -> Path:
    return Path(
        path or os.environ.get("TRQ_UNIVERSE_CACHE_PATH", DEFAULT_CACHE_PATH)
    )
