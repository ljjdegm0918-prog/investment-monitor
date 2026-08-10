"""Sweden (SE) tradeable universe cache (breadth only) - boundary stub.

SE-2 spike (2026-08-10) found no stable key-free official directory for
Nasdaq Stockholm equities:

* ``nasdaqomxnordic.com/shares/listed-companies/stockholm`` and
  ``.../first-north-sweden`` are Drupal SPAs: the server-rendered HTML
  contains no company rows (no ISIN/name cells); the directory is powered
  by a JS screener component (``nasdaq-market-data-api-screener`` with
  ``data-endpoint="/screener/shares"`` and ``data-market="nordic"``).
* The screener data route is not publicly reachable without browser JS:
  ``api.nasdaq.com/api/screener/shares`` returns 404 and
  ``api.nasdaq.com/api/screener/stocks`` returns zero rows for every
  Stockholm/OMX exchange code tried (STO/OME/OMX/SWE/NORDIC/ST/FNS);
  ``nasdaqomxnordic.com/screener/shares`` returns the SPA shell.
* FI (Finansinspektionen) publishes no securities directory; its public
  publication client only covers insider transactions.
* A hand-written OMXS30 list would be exactly the forbidden "OMXS30 seed
  pretending to be the full universe", so none is shipped.

The cache shape is still provided: ``load_se_universe`` /
``se_universe_name_map`` / ``search_se_universe`` read a locally cached
JSON payload if one ever exists (e.g. a future Nasdaq Stockholm directory
slice), and ``refresh_se_universe`` raises ``SeUniverseError`` instead of
faking a refresh. The cache is breadth only and never flows into
information_items.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, List, Mapping, Optional

DEFAULT_CACHE_PATH = ".cache/investment_monitor/se_universe.json"


class SeUniverseError(RuntimeError):
    """Raised when the SE universe cannot be refreshed at all."""


def load_se_universe(
    path: Optional[Path] = None,
) -> Optional[Mapping[str, Any]]:
    """Load a cached SE universe payload, or None when absent/invalid."""
    cache_path = _cache_path(path)
    try:
        with cache_path.open("r", encoding="utf-8") as cache_file:
            return json.load(cache_file)
    except (OSError, json.JSONDecodeError):
        return None


def refresh_se_universe(
    *,
    path: Optional[Path] = None,
    opener=None,
    refreshed_at: Optional[str] = None,
) -> Mapping[str, Any]:
    """Refresh the SE universe.

    No free Nasdaq Stockholm directory source is wired (SE-2 spike B2), so
    this always raises ``SeUniverseError`` with the spike evidence instead
    of producing a fake or OMXS30-only universe. The cache shape is
    reserved for a future slice that lands a real Nasdaq/FI directory.
    """
    raise SeUniverseError(
        "SE universe refresh is not wired: SE-2 spike found no stable "
        "key-free Nasdaq Stockholm securities directory (Drupal SPA "
        "screener without a reachable public JSON route; api.nasdaq.com "
        "does not cover Stockholm; FI has no securities directory). See "
        "README Sweden section."
    )


def se_universe_name_map(
    path: Optional[Path] = None,
) -> Mapping[str, Mapping[str, str]]:
    """Return normalized ticker -> {name, exchange, board, isin}."""
    payload = load_se_universe(path)
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
            or "Nasdaq Stockholm Main Market"
        )
        result[ticker] = {
            "name": str(item.get("name") or ticker),
            "exchange": board,
            "board": board,
            "isin": str(item.get("isin") or ""),
        }
    return result


def search_se_universe(
    query: str,
    path: Optional[Path] = None,
) -> List[Mapping[str, Any]]:
    """Search the cached SE universe by ticker, name, ISIN or board."""
    payload = load_se_universe(path)
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
        path or os.environ.get("SE_UNIVERSE_CACHE_PATH", DEFAULT_CACHE_PATH)
    )
