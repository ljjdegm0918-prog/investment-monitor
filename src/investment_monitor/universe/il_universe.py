# -*- coding: utf-8 -*-
"""Israel (IL) tradeable universe cache (boundary stub placeholder).

The final source decision follows the live recon results; when no stable
key-free TASE directory endpoint exists, refresh raises ``IlUniverseError``
and only a manually placed cache
(``.cache/investment_monitor/il_universe.json``) is read. No TA-35 or
other hand-written seed is shipped and the cache never flows into the
information feed.
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional

from ..web_repository import normalize_il_ticker

LOGGER = logging.getLogger(__name__)

DEFAULT_CACHE_PATH = ".cache/investment_monitor/il_universe.json"


class IlUniverseError(RuntimeError):
    """Raised when the IL universe cannot be refreshed at all."""


def _cache_path(path: Optional[Path]) -> Path:
    return Path(
        path or os.environ.get("IL_UNIVERSE_CACHE_PATH", DEFAULT_CACHE_PATH)
    )


def load_il_universe(path: Optional[Path] = None) -> Optional[Mapping[str, Any]]:
    cache_file = _cache_path(path)
    if not cache_file.exists():
        return None
    try:
        with cache_file.open(encoding="utf-8") as handle:
            return json.load(handle)
    except (OSError, json.JSONDecodeError):
        return None


def refresh_il_universe() -> Mapping[str, Any]:
    raise IlUniverseError(
        "No stable key-free TASE directory endpoint; "
        "place a manually fetched il_universe.json cache instead."
    )


def il_universe_name_map(
    path: Optional[Path] = None,
) -> Mapping[str, Mapping[str, str]]:
    payload = load_il_universe(path)
    if not payload:
        return {}
    result: Dict[str, Mapping[str, str]] = {}
    for item in payload.get("items") or []:
        ticker = normalize_il_ticker(str(item.get("ticker") or ""))
        if not ticker:
            continue
        result[ticker] = {
            "name": str(item.get("name") or ticker),
            "exchange": str(item.get("exchange") or "TASE"),
            "board": str(item.get("board") or "TASE"),
            "isin": str(item.get("isin") or ""),
        }
    return result


def search_il_universe(
    query: str,
    path: Optional[Path] = None,
) -> List[Mapping[str, Any]]:
    payload = load_il_universe(path)
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
