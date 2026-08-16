# -*- coding: utf-8 -*-
"""Nasdaq Baltic tradeable universe cache (breadth only).

Source (live verified 2026-08-15): the official key-free share-list XLSX
download at ``https://nasdaqbaltic.com/statistics/en/shares?download=1``
(one row per listed instrument with columns Ticker / Name / ISIN / Currency /
MarketPlace / List/segment / ...). MarketPlace is ``TLN`` (Tallinn),
``RIG`` (Riga) or ``VLN`` (Vilnius) and is mapped to market codes
``ee`` / ``lv`` / ``lt``. The cache is breadth only and never flows into
information_items / Today feed; it exists so issuer announcements can be
matched by exact normalized company name and so add-company can backfill
name/board/ISIN. No hand-written blue-chip seed is shipped.
"""

from __future__ import annotations

import json
import io
import logging
import os
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Mapping, Optional, Tuple
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
import zipfile
from xml.etree import ElementTree

from ..web_repository import (
    normalize_ee_ticker,
    normalize_lt_ticker,
    normalize_lv_ticker,
)

LOGGER = logging.getLogger(__name__)

DEFAULT_CACHE_PATH = ".cache/investment_monitor/baltic_universe.json"
DEFAULT_DOWNLOAD_URL = "https://nasdaqbaltic.com/statistics/en/shares?download=1"
DOWNLOAD_URL_ENV = "BALTIC_UNIVERSE_DOWNLOAD_URL"
DEFAULT_USER_AGENT = "InvestmentMonitor/0.1 (internal workspace)"

MARKET_PLACES = {
    "TLN": "ee",
    "RIG": "lv",
    "VLN": "lt",
}
_NORMALIZERS = {
    "ee": normalize_ee_ticker,
    "lv": normalize_lv_ticker,
    "lt": normalize_lt_ticker,
}


class BalticUniverseError(RuntimeError):
    """Raised when the Baltic universe cannot be refreshed at all."""


def _environment_float(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, str(default)))
    except ValueError as error:
        raise ValueError(f"{name} must be numeric") from error


def load_baltic_universe(
    path: Optional[Path] = None,
) -> Optional[Mapping[str, Any]]:
    cache = Path(path or DEFAULT_CACHE_PATH)
    if not cache.exists():
        return None
    try:
        payload = json.loads(cache.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict) or "markets" not in payload:
        return None
    return payload


def refresh_baltic_universe(
    *,
    opener: Callable[..., Any] = urlopen,
    timeout: float = 30.0,
    cache_path: Optional[Path] = None,
) -> Mapping[str, Any]:
    url = os.environ.get(DOWNLOAD_URL_ENV, DEFAULT_DOWNLOAD_URL)
    request = Request(url, headers={"User-Agent": DEFAULT_USER_AGENT})
    try:
        with opener(request, timeout=timeout) as response:
            payload_bytes = response.read()
    except (HTTPError, URLError, TimeoutError, OSError) as error:
        raise BalticUniverseError(
            "Nasdaq Baltic share list download failed."
        ) from error
    try:
        rows = _parse_xlsx(payload_bytes)
    except (zipfile.BadZipFile, KeyError, ElementTree.ParseError, ValueError) as error:
        raise BalticUniverseError(
            "Nasdaq Baltic share list XLSX could not be parsed."
        ) from error
    payload = _build_payload(rows, url)
    cache = Path(cache_path or DEFAULT_CACHE_PATH)
    cache.parent.mkdir(parents=True, exist_ok=True)
    temporary = cache.with_suffix(".tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8"
    )
    temporary.replace(cache)
    return payload


def _parse_xlsx(data: bytes) -> List[List[str]]:
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        shared_root = ElementTree.fromstring(archive.read("xl/sharedStrings.xml"))
        namespace = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
        strings = [
            "".join(node.text or "" for node in item.iter(namespace + "t"))
            for item in shared_root
        ]
        sheet_root = ElementTree.fromstring(
            archive.read("xl/worksheets/sheet1.xml")
        )
        rows: List[List[str]] = []
        for row_node in sheet_root.iter(namespace + "row"):
            cells = list(row_node.iter(namespace + "c"))
            values: List[str] = []
            for cell in cells:
                reference = cell.attrib.get("r") or ""
                column = re.match(r"[A-Z]+", reference)
                column_index = _column_index(column.group(0)) if column else 0
                while len(values) < column_index:
                    values.append("")
                cell_type = cell.attrib.get("t")
                value_node = cell.find(namespace + "v")
                if cell_type == "s" and value_node is not None:
                    try:
                        values.append(strings[int(value_node.text or "0")])
                    except (ValueError, IndexError):
                        values.append("")
                elif cell_type == "inlineStr":
                    inline = cell.find(namespace + "is/" + namespace + "t")
                    values.append(inline.text or "" if inline is not None else "")
                else:
                    values.append(value_node.text or "" if value_node is not None else "")
            if any(value.strip() for value in values):
                rows.append(values)
        return rows


def _column_index(reference: str) -> int:
    index = 0
    for character in reference:
        index = index * 26 + (ord(character) - ord("A") + 1)
    return index - 1


def _build_payload(rows: List[List[str]], source_url: str) -> Mapping[str, Any]:
    if not rows:
        raise BalticUniverseError("Nasdaq Baltic share list is empty.")
    header = [str(cell).strip().lower() for cell in rows[0]]
    try:
        ticker_index = header.index("ticker")
        name_index = header.index("name")
        isin_index = header.index("isin")
        place_index = header.index("marketplace")
        board_index = header.index("list/segment")
    except ValueError as error:
        raise BalticUniverseError(
            "Nasdaq Baltic share list XLSX columns changed."
        ) from error
    markets: Dict[str, List[Dict[str, str]]] = {"ee": [], "lv": [], "lt": []}
    seen: set[Tuple[str, str]] = set()
    for row in rows[1:]:
        padded = row + [""] * (max(ticker_index, name_index, isin_index, place_index, board_index) + 1 - len(row))
        place = str(padded[place_index]).strip().upper()
        market = MARKET_PLACES.get(place)
        if market is None:
            continue
        raw_ticker = str(padded[ticker_index]).strip().upper()
        if not raw_ticker:
            continue
        ticker = _NORMALIZERS[market](raw_ticker)
        isin = str(padded[isin_index]).strip().upper()
        name = str(padded[name_index]).strip()
        board = str(padded[board_index]).strip()
        key = (ticker, market)
        if key in seen:
            continue
        seen.add(key)
        markets[market].append({
            "ticker": ticker,
            "name": name,
            "isin": isin,
            "board": board,
        })
    for market in markets:
        markets[market].sort(key=lambda entry: entry["ticker"])
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source_url": source_url,
        "markets": markets,
    }


def _entries_for(market: str) -> Optional[Tuple[Dict[str, str], ...]]:
    payload = load_baltic_universe()
    if payload is None:
        return None
    markets = payload.get("markets")
    if not isinstance(markets, dict):
        return None
    entries = markets.get(market)
    if not isinstance(entries, list):
        return None
    return tuple(
        {
            "ticker": str(entry.get("ticker") or ""),
            "name": str(entry.get("name") or ""),
            "isin": str(entry.get("isin") or ""),
            "board": str(entry.get("board") or ""),
        }
        for entry in entries
        if entry.get("ticker")
    )


def baltic_universe_name_map(
    market: str,
) -> Optional[Mapping[str, Mapping[str, str]]]:
    """Return {ticker: {name, isin, board}} for one Baltic market, or None."""
    entries = _entries_for(market)
    if entries is None:
        return None
    return {
        entry["ticker"]: {
            "name": entry["name"],
            "isin": entry["isin"],
            "board": entry["board"],
        }
        for entry in entries
    }


def ee_universe_name_map() -> Optional[Mapping[str, Mapping[str, str]]]:
    return baltic_universe_name_map("ee")


def lv_universe_name_map() -> Optional[Mapping[str, Mapping[str, str]]]:
    return baltic_universe_name_map("lv")


def lt_universe_name_map() -> Optional[Mapping[str, Mapping[str, str]]]:
    return baltic_universe_name_map("lt")


def search_baltic_universe(market: str, term: str) -> Tuple[Dict[str, str], ...]:
    entries = _entries_for(market) or ()
    needle = term.strip().casefold()
    if not needle:
        return entries
    return tuple(
        entry
        for entry in entries
        if needle in entry["ticker"].casefold()
        or needle in entry["name"].casefold()
        or needle in entry["isin"].casefold()
    )


__all__ = [
    "BalticUniverseError",
    "baltic_universe_name_map",
    "ee_universe_name_map",
    "load_baltic_universe",
    "lt_universe_name_map",
    "lv_universe_name_map",
    "refresh_baltic_universe",
    "search_baltic_universe",
]
