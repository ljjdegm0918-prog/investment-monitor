# -*- coding: utf-8 -*-
"""India (IN) tradeable universe cache from the official NSE equity CSV.

Source (live verified 2026-08-15): the classic key-free NSE equity list
CSV at ``https://archives.nseindia.com/content/equities/EQUITY_L.csv``
(columns SYMBOL, NAME OF COMPANY, SERIES, DATE OF LISTING, PAID UP VALUE,
MARKET LOT, ISIN NUMBER, FACE VALUE). Only ``SERIES == EQ`` rows are kept
so the universe is the equity tradeable list; BSE-only listings are NOT
mixed in (BSE is a separate second-disclosure boundary). No Nifty50
hand-written seed is shipped and the cache never flows into the feed.
"""

from __future__ import annotations

import csv
import io
import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Mapping, Optional
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from ..web_repository import normalize_in_ticker

LOGGER = logging.getLogger(__name__)

DEFAULT_CACHE_PATH = ".cache/investment_monitor/in_universe.json"
DIRECTORY_URL = "https://archives.nseindia.com/content/equities/EQUITY_L.csv"
DIRECTORY_URL_ENV = "IN_UNIVERSE_DIRECTORY_URL"


class InUniverseError(RuntimeError):
    """Raised when the IN universe cannot be refreshed at all."""


def _cache_path(path: Optional[Path]) -> Path:
    return Path(
        path or os.environ.get("IN_UNIVERSE_CACHE_PATH", DEFAULT_CACHE_PATH)
    )


def load_in_universe(path: Optional[Path] = None) -> Optional[Mapping[str, Any]]:
    cache_file = _cache_path(path)
    if not cache_file.exists():
        return None
    try:
        with cache_file.open(encoding="utf-8") as handle:
            return json.load(handle)
    except (OSError, json.JSONDecodeError):
        return None


def refresh_in_universe(
    *,
    path: Optional[Path] = None,
    opener: Optional[Callable[..., Any]] = None,
    url: Optional[str] = None,
    refreshed_at: Optional[str] = None,
) -> Mapping[str, Any]:
    cache_path = _cache_path(path)
    directory_url = url or os.environ.get(DIRECTORY_URL_ENV, DIRECTORY_URL)
    request = Request(
        directory_url,
        headers={
            "User-Agent": "Mozilla/5.0 (compatible; InvestmentMonitor/0.1)",
            "Accept": "text/csv",
        },
    )
    try:
        with (opener or urlopen)(request, timeout=60) as response:
            raw = response.read()
    except (HTTPError, URLError, TimeoutError, OSError) as error:
        raise InUniverseError(f"NSE equity list failed: {error}") from error
    try:
        rows = _parse_csv(raw)
    except (csv.Error, UnicodeDecodeError) as error:
        raise InUniverseError("NSE equity list CSV could not be parsed.") from error
    if not rows:
        raise InUniverseError("NSE equity list returned no EQ rows.")
    payload = {
        "updated_at": refreshed_at or datetime.now(timezone.utc).isoformat(),
        "source": ["nse_equity_list_csv"],
        "counts": {"EQ": len(rows)},
        "items": rows,
    }
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = cache_path.with_suffix(cache_path.suffix + ".tmp")
    with temporary_path.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False)
    temporary_path.replace(cache_path)
    return payload


def _parse_csv(raw: bytes) -> List[Mapping[str, Any]]:
    text = raw.decode("utf-8-sig", errors="replace")
    reader = csv.reader(io.StringIO(text))
    header = None
    rows: List[Mapping[str, Any]] = []
    for row in reader:
        if not row or not row[0]:
            continue
        if header is None:
            header = [cell.strip().lower() for cell in row]
            continue
        record = {header[i]: row[i].strip() for i in range(min(len(header), len(row)))}
        series = str(record.get("series") or "").strip().upper()
        if series != "EQ":
            continue
        symbol = normalize_in_ticker(str(record.get("symbol") or ""))
        if not symbol:
            continue
        rows.append({
            "ticker": symbol,
            "name": str(record.get("name of company") or symbol),
            "isin": str(record.get("isin number") or ""),
            "board": "NSE EQ",
            "series": "EQ",
        })
    return sorted(rows, key=lambda item: item["ticker"])


def in_universe_name_map(
    path: Optional[Path] = None,
) -> Mapping[str, Mapping[str, str]]:
    payload = load_in_universe(path)
    if not payload:
        return {}
    result: Dict[str, Mapping[str, str]] = {}
    for item in payload.get("items") or []:
        ticker = str(item.get("ticker") or "").strip()
        if not ticker:
            continue
        result[ticker] = {
            "name": str(item.get("name") or ticker),
            "exchange": "NSE",
            "board": str(item.get("board") or "NSE EQ"),
            "isin": str(item.get("isin") or ""),
        }
    return result


def search_in_universe(
    query: str,
    path: Optional[Path] = None,
) -> List[Mapping[str, Any]]:
    payload = load_in_universe(path)
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
