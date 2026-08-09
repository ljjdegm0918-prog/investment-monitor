"""IT tradeable universe cache (breadth only) from the Euronext live CSV.

Source (live verified 2026-08-10): the same key-free Euronext live "all
stocks" CSV download used by the FR/NL universes
(``live.euronext.com/en/pd_es/data/stocks/download?mics=dm_all_stock``).
Rows whose market segment mentions Milan are kept: ``Euronext Milan``
(~204) and ``Euronext Growth Milan`` (~243). No ``Borsa Italiana`` /
``Milano`` labels appear in the current feed; the filter also accepts them
so future label changes stay honest. Non-Italian national boards, Euronext
Global Equity Market (``1*``), Trading After Hours (``2*``) and EuroTLX
(``4*``) are excluded.

The cache is breadth only and never flows into information_items / Today
feed. Each entry stores name/ISIN under the normalized IT ticker so the
IT-1 EQS connector can align by ISIN once the universe is refreshed.
"""

from __future__ import annotations

import csv
import io
import json
import logging
import os
import ssl
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Mapping, Optional
from urllib.request import HTTPSHandler, Request, build_opener, urlopen

from ..web_repository import normalize_it_ticker

LOGGER = logging.getLogger(__name__)

DEFAULT_CACHE_PATH = ".cache/investment_monitor/it_universe.json"
DIRECTORY_URL = (
    "https://live.euronext.com/en/pd_es/data/stocks/download"
    "?mics=dm_all_stock"
)
DIRECTORY_URL_ENV = "IT_UNIVERSE_DIRECTORY_URL"
DEFAULT_USER_AGENT = "InvestmentMonitor/0.1 (internal workspace)"


class ItUniverseError(RuntimeError):
    """Raised when the IT universe cannot be refreshed at all."""


def load_it_universe(
    path: Optional[Path] = None,
) -> Optional[Mapping[str, Any]]:
    """Load the cached universe payload, or None when absent/invalid."""
    cache_path = _cache_path(path)
    try:
        with cache_path.open("r", encoding="utf-8") as cache_file:
            return json.load(cache_file)
    except (OSError, json.JSONDecodeError):
        return None


def refresh_it_universe(
    *,
    path: Optional[Path] = None,
    opener: Optional[Callable[..., Any]] = None,
    url: Optional[str] = None,
    refreshed_at: Optional[str] = None,
) -> Mapping[str, Any]:
    """Refresh the IT universe from the Euronext live all-stocks CSV.

    Rows whose market segment mentions Milan (or Borsa Italiana / Milano
    labels if they ever appear) are kept; other venues are dropped. A full
    failure (network or no parseable Milan rows) raises ``ItUniverseError``.
    The cache is written atomically (tmp + replace).
    """
    cache_path = _cache_path(path)
    verify_ssl = (
        os.environ.get("IT_UNIVERSE_VERIFY_SSL", "true")
        .strip()
        .lower()
    ) not in {"0", "false", "no", "off"}
    default_opener = _make_opener(verify_ssl)
    directory_url = url or os.environ.get(DIRECTORY_URL_ENV, DIRECTORY_URL)

    try:
        rows = _fetch_directory_rows(
            directory_url,
            opener or default_opener,
        )
    except Exception as error:
        LOGGER.warning(
            "it_universe source=euronext_live_csv failed: %s",
            error,
        )
        raise ItUniverseError(
            f"Euronext live stock list failed: {error}"
        ) from error

    entries: Dict[str, Mapping[str, Any]] = {}
    counts: Dict[str, int] = {}
    for row in rows:
        ticker = str(row.get("ticker") or "")
        if not ticker or ticker in entries:
            continue
        board = str(row.get("market") or "Euronext Milan")
        entries[ticker] = {
            "ticker": ticker,
            "name": str(row.get("name") or ticker),
            "isin": str(row.get("isin") or ""),
            "board": board,
            "exchange": board,
            "status": "active",
        }
        counts[board] = counts.get(board, 0) + 1

    if not entries:
        raise ItUniverseError(
            "IT universe source failed; no Milan entries available."
        )

    payload = {
        "updated_at": (
            refreshed_at
            or datetime.now(timezone.utc).isoformat()
        ),
        "source": ["euronext_live_csv"],
        "counts": counts,
        "items": sorted(
            entries.values(),
            key=lambda item: item["ticker"],
        ),
    }
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = cache_path.with_suffix(cache_path.suffix + ".tmp")
    with temporary_path.open("w", encoding="utf-8") as cache_file:
        json.dump(payload, cache_file, ensure_ascii=False)
    temporary_path.replace(cache_path)
    return payload


def it_universe_name_map(
    path: Optional[Path] = None,
) -> Mapping[str, Mapping[str, str]]:
    """Return normalized ticker -> {name, exchange, board, isin}."""
    payload = load_it_universe(path)
    if not payload:
        return {}
    result: Dict[str, Mapping[str, str]] = {}
    for item in payload.get("items") or []:
        ticker = str(item.get("ticker") or "").strip()
        if not ticker:
            continue
        board = str(
            item.get("board")
            or item.get("exchange")
            or "Euronext Milan"
        )
        result[ticker] = {
            "name": str(item.get("name") or ticker),
            "exchange": board,
            "board": board,
            "isin": str(item.get("isin") or ""),
        }
    return result


def search_it_universe(
    query: str,
    path: Optional[Path] = None,
) -> List[Mapping[str, Any]]:
    """Search the cached IT universe by ticker, name, ISIN or board."""
    payload = load_it_universe(path)
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


def _fetch_directory_rows(
    url: str,
    opener: Callable[..., Any],
) -> List[Mapping[str, Any]]:
    raw = _get_csv(url, opener)
    reader = csv.reader(io.StringIO(raw), delimiter=";")
    records: List[Mapping[str, Any]] = []
    seen_header = False
    for row in reader:
        if not row or not row[0]:
            continue
        if not seen_header:
            if str(row[0]).strip() == "Name" and len(row) >= 5:
                seen_header = True
            continue
        if len(row) < 5:
            continue
        market = str(row[3]).strip()
        if not _is_italian_board(market):
            continue
        symbol = str(row[2]).strip()
        if not symbol or symbol == "-":
            continue
        ticker = normalize_it_ticker(symbol)
        if not ticker:
            continue
        records.append(
            {
                "ticker": ticker,
                "name": str(row[0]).strip(),
                "isin": str(row[1]).strip(),
                "market": market,
            }
        )
    if not records:
        raise ItUniverseError(
            "Euronext live CSV returned no parseable Milan entries."
        )
    return records


def _is_italian_board(market: str) -> bool:
    lowered = market.casefold()
    return (
        "milan" in lowered
        or "borsa italiana" in lowered
        or "milano" in lowered
    )


def _get_csv(
    url: str,
    opener: Callable[..., Any],
) -> str:
    request = Request(
        url,
        headers={
            "User-Agent": DEFAULT_USER_AGENT,
            "Accept": "text/csv",
            "Accept-Language": "en,it;q=0.8",
        },
        method="GET",
    )
    with opener(request, timeout=60) as response:
        raw = response.read()
    return raw.decode("utf-8-sig", errors="replace")


def _make_opener(verify_ssl: bool) -> Callable[..., Any]:
    if verify_ssl:
        return urlopen
    return build_opener(
        HTTPSHandler(context=ssl._create_unverified_context())
    ).open


def _cache_path(path: Optional[Path]) -> Path:
    return Path(
        path or os.environ.get("IT_UNIVERSE_CACHE_PATH", DEFAULT_CACHE_PATH)
    )
