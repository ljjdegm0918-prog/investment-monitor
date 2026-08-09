"""SG tradeable universe cache (breadth only) - boundary stub.

SG-2 spike (2026-08-10) found no stable key-free official directory for
SGX equities:

* SGX listed-company pages (``www.sgx.com/securities/*``) are a JS SPA; the
  stock screener is powered by Refinitiv/LSEG and has no documented public
  JSON/CSV export.
* ``api.sgx.com`` routes return 403 (undocumented AWS Gateway; no stable
  free list endpoint; SGX DataLink is a paid market-data product and is not
  used).
* ``data.gov.sg`` holds only aggregate SINGSTAT turnover for SGX boards,
  not a securities directory; the ACRA registry is the full company
  register (no SGX ticker/board/ISIN).
* A hand-written STI list would be exactly the forbidden "STI seed
  pretending to be the full universe", so none is shipped.

The cache shape is still provided: ``load_sg_universe`` /
``sg_universe_name_map`` / ``search_sg_universe`` read a locally cached
JSON payload if one ever exists (e.g. a future SGX directory slice), and
``refresh_sg_universe`` raises ``SgUniverseError`` instead of faking a
refresh. The cache is breadth only and never flows into information_items.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, List, Mapping, Optional

DEFAULT_CACHE_PATH = ".cache/investment_monitor/sg_universe.json"


class SgUniverseError(RuntimeError):
    """Raised when the SG universe cannot be refreshed at all."""


def load_sg_universe(
    path: Optional[Path] = None,
) -> Optional[Mapping[str, Any]]:
    """Load a cached SG universe payload, or None when absent/invalid."""
    cache_path = _cache_path(path)
    try:
        with cache_path.open("r", encoding="utf-8") as cache_file:
            return json.load(cache_file)
    except (OSError, json.JSONDecodeError):
        return None


def refresh_sg_universe(
    *,
    path: Optional[Path] = None,
    opener=None,
    refreshed_at: Optional[str] = None,
) -> Mapping[str, Any]:
    """Refresh the SG universe.

    No free SGX directory source is wired (SG-2 spike B2), so this always
    raises ``SgUniverseError`` with the spike evidence instead of producing
    a fake or STI-only universe. The cache shape is reserved for a future
    slice that lands a real SGX/regulator directory.
    """
    raise SgUniverseError(
        "SG universe refresh is not wired: SG-2 spike found no stable "
        "key-free SGX securities directory (SPA/Refinitiv screener, "
        "api.sgx.com 403, data.gov.sg aggregate-only, ACRA full-registry "
        "without SGX codes). See README Singapore section."
    )


def sg_universe_name_map(
    path: Optional[Path] = None,
) -> Mapping[str, Mapping[str, str]]:
    """Return normalized ticker -> {name, exchange, board, isin}."""
    payload = load_sg_universe(path)
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
            or "SGX Mainboard"
        )
        result[ticker] = {
            "name": str(item.get("name") or ticker),
            "exchange": board,
            "board": board,
            "isin": str(item.get("isin") or ""),
        }
    return result


def search_sg_universe(
    query: str,
    path: Optional[Path] = None,
) -> List[Mapping[str, Any]]:
    """Search the cached SG universe by ticker, name, ISIN or board."""
    payload = load_sg_universe(path)
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
        path or os.environ.get("SG_UNIVERSE_CACHE_PATH", DEFAULT_CACHE_PATH)
    )
