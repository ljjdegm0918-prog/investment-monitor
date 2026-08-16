# -*- coding: utf-8 -*-
"""NO tradeable universe cache (breadth only) from the Euronext live CSV.

Source (live verified 2026-08-10 for the shared CSV): the key-free
Euronext live all-stocks CSV
(``live.euronext.com/en/pd_es/data/stocks/download?mics=dm_all_stock``).
Only rows whose market segment mentions ``Euronext Oslo`` are kept, which
is the live-locked venue evidence that this is the Oslo Bors table and not
an Amsterdam/Paris/Brussels/Lisbon filter mistake. No OBX hand-written
seed is shipped and the cache never flows into the information feed.
"""

from __future__ import annotations

import json
import logging
import os
import ssl
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Mapping, Optional
from urllib.error import HTTPError, URLError
from urllib.request import HTTPSHandler, build_opener, urlopen

from ..web_repository import normalize_no_ticker
from .euronext_common import (
    build_universe_payload,
    fetch_euronext_rows,
    write_universe_cache,
)

LOGGER = logging.getLogger(__name__)

DEFAULT_CACHE_PATH = ".cache/investment_monitor/no_universe.json"
DIRECTORY_URL = (
    "https://live.euronext.com/en/pd_es/data/stocks/download"
    "?mics=dm_all_stock"
)
DIRECTORY_URL_ENV = "NO_UNIVERSE_DIRECTORY_URL"
VENUE = "Oslo"


class NoUniverseError(RuntimeError):
    """Raised when the NO universe cannot be refreshed at all."""


def _cache_path(path: Optional[Path]) -> Path:
    return Path(
        path or os.environ.get("NO_UNIVERSE_CACHE_PATH", DEFAULT_CACHE_PATH)
    )


def load_no_universe(path: Optional[Path] = None) -> Optional[Mapping[str, Any]]:
    cache_file = _cache_path(path)
    if not cache_file.exists():
        return None
    try:
        with cache_file.open(encoding="utf-8") as handle:
            return json.load(handle)
    except (OSError, json.JSONDecodeError):
        return None


def refresh_no_universe(
    *,
    path: Optional[Path] = None,
    opener: Optional[Callable[..., Any]] = None,
    url: Optional[str] = None,
    refreshed_at: Optional[str] = None,
) -> Mapping[str, Any]:
    cache_path = _cache_path(path)
    verify_ssl = (
        os.environ.get("NO_UNIVERSE_VERIFY_SSL", "true").strip().lower()
    ) not in {"0", "false", "no", "off"}
    default_opener = (
        urlopen
        if verify_ssl
        else build_opener(
            HTTPSHandler(context=ssl._create_unverified_context())
        ).open
    )
    directory_url = url or os.environ.get(DIRECTORY_URL_ENV, DIRECTORY_URL)
    try:
        rows = fetch_euronext_rows(
            directory_url, opener or default_opener, VENUE
        )
    except (HTTPError, URLError, TimeoutError, OSError) as error:
        raise NoUniverseError(
            f"Euronext live stock list failed: {error}"
        ) from error
    if not rows:
        raise NoUniverseError(
            "NO universe source failed; no Euronext Oslo entries available."
        )
    payload = build_universe_payload(
        rows, normalize_no_ticker, "euronext_live_csv_no", refreshed_at
    )
    write_universe_cache(cache_path, payload)
    return payload


def no_universe_name_map(
    path: Optional[Path] = None,
) -> Mapping[str, Mapping[str, str]]:
    payload = load_no_universe(path)
    if not payload:
        return {}
    result: Dict[str, Mapping[str, str]] = {}
    for item in payload.get("items") or []:
        ticker = str(item.get("ticker") or "").strip()
        if not ticker:
            continue
        board = str(item.get("board") or item.get("exchange") or "Euronext Oslo")
        result[ticker] = {
            "name": str(item.get("name") or ticker),
            "exchange": board,
            "board": board,
            "isin": str(item.get("isin") or ""),
        }
    return result


def search_no_universe(
    query: str,
    path: Optional[Path] = None,
) -> List[Mapping[str, Any]]:
    payload = load_no_universe(path)
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
