# -*- coding: utf-8 -*-
"""Mexico (MX) tradeable universe cache (boundary stub).

Recon (2026-08-15): BMV does not expose a stable key-free machine-readable
company directory (deep paths 404; no CSV/XLSX/JSON found). No IPC or
other hand-written seed is shipped: refresh raises ``MxUniverseError`` and
only a manually placed cache (``.cache/investment_monitor/mx_universe.json``)
would ever be read. The cache never flows into the information feed.
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional

from ..web_repository import normalize_mx_ticker

LOGGER = logging.getLogger(__name__)

DEFAULT_CACHE_PATH = ".cache/investment_monitor/mx_universe.json"


class MxUniverseError(RuntimeError):
    """Raised when the MX universe cannot be refreshed at all."""


def _cache_path(path: Optional[Path]) -> Path:
    return Path(
        path or os.environ.get("MX_UNIVERSE_CACHE_PATH", DEFAULT_CACHE_PATH)
    )


def load_mx_universe(path: Optional[Path] = None) -> Optional[Mapping[str, Any]]:
    cache_file = _cache_path(path)
    if not cache_file.exists():
        return None
    try:
        with cache_file.open(encoding="utf-8") as handle:
            return json.load(handle)
    except (OSError, json.JSONDecodeError):
        return None


def refresh_mx_universe() -> Mapping[str, Any]:
    raise MxUniverseError(
        "No stable key-free BMV directory endpoint; "
        "place a manually fetched mx_universe.json cache instead."
    )


def mx_universe_name_map(
    path: Optional[Path] = None,
) -> Mapping[str, Mapping[str, str]]:
    payload = load_mx_universe(path)
    if not payload:
        return {}
    result: Dict[str, Mapping[str, str]] = {}
    for item in payload.get("items") or []:
        ticker = normalize_mx_ticker(str(item.get("ticker") or ""))
        if not ticker:
            continue
        result[ticker] = {
            "name": str(item.get("name") or ticker),
            "exchange": str(item.get("exchange") or "BMV"),
            "board": str(item.get("board") or "BMV"),
            "isin": str(item.get("isin") or ""),
        }
    return result


def search_mx_universe(
    query: str,
    path: Optional[Path] = None,
) -> List[Mapping[str, Any]]:
    payload = load_mx_universe(path)
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
