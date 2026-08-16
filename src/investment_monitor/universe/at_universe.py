# -*- coding: utf-8 -*-
"""Austria (AT) tradeable universe cache (boundary stub).

Recon (2026-08-15): Wiener Börse listed-companies pages are a TYPO3 site
whose company directory is client-side rendered; no stable key-free
machine-readable directory endpoint (CSV/XLSX/JSON) was found under the
public /en/market-data/ and /en/listed-companies/ paths. No ATX or other
hand-written seed is shipped: refresh raises ``AtUniverseError`` and only
a manually placed cache (``.cache/investment_monitor/at_universe.json``)
would ever be read, so a future real directory can drop in without code
changes. The cache never flows into the information feed.
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional

from ..web_repository import normalize_at_ticker

LOGGER = logging.getLogger(__name__)

DEFAULT_CACHE_PATH = ".cache/investment_monitor/at_universe.json"


class AtUniverseError(RuntimeError):
    """Raised when the AT universe cannot be refreshed at all."""


def _cache_path(path: Optional[Path]) -> Path:
    return Path(
        path or os.environ.get("AT_UNIVERSE_CACHE_PATH", DEFAULT_CACHE_PATH)
    )


def load_at_universe(path: Optional[Path] = None) -> Optional[Mapping[str, Any]]:
    cache_file = _cache_path(path)
    if not cache_file.exists():
        return None
    try:
        with cache_file.open(encoding="utf-8") as handle:
            return json.load(handle)
    except (OSError, json.JSONDecodeError):
        return None


def refresh_at_universe() -> Mapping[str, Any]:
    raise AtUniverseError(
        "No stable key-free Wiener Börse directory endpoint; "
        "place a manually fetched at_universe.json cache instead."
    )


def at_universe_name_map(
    path: Optional[Path] = None,
) -> Mapping[str, Mapping[str, str]]:
    payload = load_at_universe(path)
    if not payload:
        return {}
    result: Dict[str, Mapping[str, str]] = {}
    for item in payload.get("items") or []:
        ticker = normalize_at_ticker(str(item.get("ticker") or ""))
        if not ticker:
            continue
        result[ticker] = {
            "name": str(item.get("name") or ticker),
            "exchange": str(item.get("exchange") or "Wiener Börse"),
            "board": str(item.get("board") or "Wiener Börse"),
            "isin": str(item.get("isin") or ""),
        }
    return result


def search_at_universe(
    query: str,
    path: Optional[Path] = None,
) -> List[Mapping[str, Any]]:
    payload = load_at_universe(path)
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
