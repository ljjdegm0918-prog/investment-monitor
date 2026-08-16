# -*- coding: utf-8 -*-
"""Hungary (HU) tradeable universe cache (boundary stub placeholder).

Final source decision follows the live recon results; when no stable
key-free BSE/BET directory endpoint exists, refresh raises
``HuUniverseError`` and only a manually placed cache
(``.cache/investment_monitor/hu_universe.json``) is read. No BUX or other
hand-written seed is shipped and the cache never flows into the feed.
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional

from ..web_repository import normalize_hu_ticker

LOGGER = logging.getLogger(__name__)

DEFAULT_CACHE_PATH = ".cache/investment_monitor/hu_universe.json"


class HuUniverseError(RuntimeError):
    """Raised when the HU universe cannot be refreshed at all."""


def _cache_path(path: Optional[Path]) -> Path:
    return Path(
        path or os.environ.get("HU_UNIVERSE_CACHE_PATH", DEFAULT_CACHE_PATH)
    )


def load_hu_universe(path: Optional[Path] = None) -> Optional[Mapping[str, Any]]:
    cache_file = _cache_path(path)
    if not cache_file.exists():
        return None
    try:
        with cache_file.open(encoding="utf-8") as handle:
            return json.load(handle)
    except (OSError, json.JSONDecodeError):
        return None


def refresh_hu_universe() -> Mapping[str, Any]:
    raise HuUniverseError(
        "No stable key-free BSE/BET directory endpoint; "
        "place a manually fetched hu_universe.json cache instead."
    )


def hu_universe_name_map(
    path: Optional[Path] = None,
) -> Mapping[str, Mapping[str, str]]:
    payload = load_hu_universe(path)
    if not payload:
        return {}
    result: Dict[str, Mapping[str, str]] = {}
    for item in payload.get("items") or []:
        ticker = normalize_hu_ticker(str(item.get("ticker") or ""))
        if not ticker:
            continue
        result[ticker] = {
            "name": str(item.get("name") or ticker),
            "exchange": str(item.get("exchange") or "BSE"),
            "board": str(item.get("board") or "BSE"),
            "isin": str(item.get("isin") or ""),
        }
    return result


def search_hu_universe(
    query: str,
    path: Optional[Path] = None,
) -> List[Mapping[str, Any]]:
    payload = load_hu_universe(path)
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
