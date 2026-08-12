"""Cboe Europe (CXE) tradeable universe cache (breadth only).

Source (live verified 2026-08-10): the key-free official Cboe Europe
"Symbol Data" CSV downloads for the two Cboe Europe equities order books:

* CXE: ``https://www.cboe.com/europe/equities/market_statistics/
  symbol_data/csv/?mkt=cxe`` - 5,305 instrument rows.
* BXE: ``https://www.cboe.com/europe/equities/market_statistics/
  symbol_data/csv/?mkt=bxe`` - 6,469 instrument rows.

Both CSVs are semicolon-free comma files with a header (``Name``,
``Company Name / Description``, quote columns). The ``Name`` column is
the case-sensitive Cboe Europe symbol (e.g. ``AZNl`` / ``SHELl`` /
``ROPz``); the CSV has **no ISIN or instrument-type column**, so entries
store the raw symbol plus an empty ISIN rather than pretending to have
one. The CSV includes zero-volume rows (3,844 of 5,305 CXE rows had zero
volume on 2026-08-10), so it is a venue symbol directory, not just the
day's traded list. This is the first "Alternative European Equities"
venue only - Turquoise and other MTFs are deferred, and no LSE/Xetra/AQSE
directory is filtered in.

The cache is breadth only and never flows into information_items / Today
feed. It backfills name / exchange / venue on add-company.
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

from ..web_repository import normalize_cxe_ticker

LOGGER = logging.getLogger(__name__)

DEFAULT_CACHE_PATH = ".cache/investment_monitor/cxe_universe.json"
CXE_URL = (
    "https://www.cboe.com/europe/equities/market_statistics/"
    "symbol_data/csv/?mkt=cxe"
)
BXE_URL = (
    "https://www.cboe.com/europe/equities/market_statistics/"
    "symbol_data/csv/?mkt=bxe"
)
CXE_URL_ENV = "CXE_UNIVERSE_CXE_URL"
BXE_URL_ENV = "CXE_UNIVERSE_BXE_URL"
DEFAULT_USER_AGENT = "InvestmentMonitor/0.1 (internal workspace)"


class CxeUniverseError(RuntimeError):
    """Raised when the CXE universe cannot be refreshed at all."""


def load_cxe_universe(
    path: Optional[Path] = None,
) -> Optional[Mapping[str, Any]]:
    """Load a cached CXE universe payload, or None when absent/invalid."""
    cache_path = _cache_path(path)
    try:
        with cache_path.open("r", encoding="utf-8") as cache_file:
            return json.load(cache_file)
    except (OSError, json.JSONDecodeError):
        return None


def refresh_cxe_universe(
    *,
    path: Optional[Path] = None,
    opener: Optional[Callable[..., Any]] = None,
    cxe_url: Optional[str] = None,
    bxe_url: Optional[str] = None,
    refreshed_at: Optional[str] = None,
) -> Mapping[str, Any]:
    """Refresh the CXE universe from the two Cboe Europe symbol CSVs.

    Each book (CXE / BXE) is fetched independently; a single-book failure
    is logged and the other book is still kept. Only when both books fail
    is ``CxeUniverseError`` raised. The cache is written atomically (tmp +
    replace) and is breadth only (never information_items). Symbols that
    appear on both books are merged into one entry with a ``venues``
    list; counts are per book and ``unique_tickers`` is the merged count.
    """
    cache_path = _cache_path(path)
    verify_ssl = (
        os.environ.get("CXE_UNIVERSE_VERIFY_SSL", "true")
        .strip()
        .lower()
    ) not in {"0", "false", "no", "off"}
    default_opener = _make_opener(verify_ssl)
    active_opener = opener or default_opener
    cxe = cxe_url or os.environ.get(CXE_URL_ENV, CXE_URL)
    bxe = bxe_url or os.environ.get(BXE_URL_ENV, BXE_URL)

    entries: Dict[str, Dict[str, Any]] = {}
    counts: Dict[str, int] = {}
    sources: List[str] = []
    failures: List[str] = []
    for venue, url in (("CXE", cxe), ("BXE", bxe)):
        try:
            rows = _fetch_symbol_rows(url, active_opener)
        except Exception as error:
            message = str(error) or error.__class__.__name__
            failures.append(f"{venue}: {message}")
            LOGGER.warning("cxe_universe venue=%s failed: %s", venue, error)
            continue
        sources.append(f"cboe_{venue.lower()}_symbol_csv")
        counts[venue] = len(rows)
        for row in rows:
            ticker = str(row.get("ticker") or "")
            if not ticker:
                continue
            existing = entries.get(ticker)
            if existing is None:
                entries[ticker] = {
                    "ticker": ticker,
                    "name": str(row.get("name") or ticker),
                    "symbol": str(row.get("symbol") or ticker),
                    "isin": "",
                    "venue": venue,
                    "venues": [venue],
                    "board": f"Cboe Europe {venue}",
                    "exchange": f"Cboe Europe {venue}",
                    "status": "active",
                }
            else:
                if venue not in existing["venues"]:
                    existing["venues"] = sorted(existing["venues"] + [venue])
                if not existing.get("name"):
                    existing["name"] = str(row.get("name") or ticker)

    if not entries:
        raise CxeUniverseError(
            "CXE universe sources failed; no Cboe Europe entries available "
            f"({'; '.join(failures) or 'no sources wired'})."
        )

    payload = {
        "updated_at": (
            refreshed_at or datetime.now(timezone.utc).isoformat()
        ),
        "source": sources,
        "counts": counts,
        "unique_tickers": len(entries),
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


def cxe_universe_name_map(
    path: Optional[Path] = None,
) -> Mapping[str, Mapping[str, str]]:
    """Return normalized ticker -> {name, exchange, board, isin, venue}."""
    payload = load_cxe_universe(path)
    if not payload:
        return {}
    result: Dict[str, Mapping[str, str]] = {}
    for item in payload.get("items") or []:
        ticker = str(item.get("ticker") or "").strip()
        if not ticker:
            continue
        board = str(item.get("board") or item.get("exchange") or "Cboe Europe")
        result[ticker] = {
            "name": str(item.get("name") or ticker),
            "exchange": board,
            "board": board,
            "isin": str(item.get("isin") or ""),
            "venue": str(item.get("venue") or ""),
        }
    return result


def search_cxe_universe(
    query: str,
    path: Optional[Path] = None,
) -> List[Mapping[str, Any]]:
    """Search the cached CXE universe by ticker, name, symbol or venue."""
    payload = load_cxe_universe(path)
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
            f"{item.get('symbol') or ''} "
            f"{item.get('venue') or ''} "
            f"{' '.join(item.get('venues') or [])}"
        ).lower()
        if needle in haystack:
            matches.append(dict(item))
        if len(matches) >= 50:
            break
    return matches


def _fetch_symbol_rows(
    url: str,
    opener: Callable[..., Any],
) -> List[Mapping[str, Any]]:
    request = Request(
        url,
        headers={
            "User-Agent": DEFAULT_USER_AGENT,
            "Accept": "text/csv,*/*",
            "Accept-Language": "en-GB,en;q=0.8",
        },
        method="GET",
    )
    with opener(request, timeout=90) as response:
        raw = response.read()
    text = raw.decode("utf-8-sig", errors="replace")
    reader = csv.reader(io.StringIO(text))
    records: List[Mapping[str, Any]] = []
    seen_header = False
    for row in reader:
        if not row:
            continue
        if not seen_header:
            if str(row[0]).strip().upper() == "NAME":
                seen_header = True
            continue
        symbol = str(row[0]).strip()
        name = str(row[1]).strip() if len(row) > 1 else ""
        if not symbol:
            continue
        ticker = normalize_cxe_ticker(symbol)
        if not ticker:
            continue
        records.append(
            {
                "ticker": ticker,
                "symbol": symbol,
                "name": name or ticker,
            }
        )
    if not records:
        raise CxeUniverseError(
            "Cboe Europe symbol CSV returned no parseable rows."
        )
    return records


def _make_opener(verify_ssl: bool) -> Callable[..., Any]:
    if verify_ssl:
        return urlopen
    return build_opener(
        HTTPSHandler(context=ssl._create_unverified_context())
    ).open


def _cache_path(path: Optional[Path]) -> Path:
    return Path(
        path or os.environ.get("CXE_UNIVERSE_CACHE_PATH", DEFAULT_CACHE_PATH)
    )
