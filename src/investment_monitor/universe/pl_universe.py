"""Poland (PL) tradeable universe cache (breadth only).

Source (live verified 2026-08-10): two key-free official GPW HTML
directories, both server-rendered tables with one row per listed company
(ISIN link, full name, mnemonic ticker in parentheses):

* GPW Main Market: ``https://www.gpw.pl/spolki?limit=403`` - 403 companies
  on the G\u0142\u00f3wny Rynek ("GPW Main Market") as of 2026-08-10.
* NewConnect: ``https://newconnect.pl/spolki?limit=403`` - 349 companies
  as of 2026-08-10 (some rows have no ISIN link; ticker/name still kept).

Both pages are plain server-rendered HTML (no JavaScript required for the
initial directory). The old ``www.gpw.pl/lista-spolek*`` URLs now return a
404 shell, and the ``ajaxindex.php`` search endpoint rejects non-browser
clients (WAF "Request Rejected"), so the cached pages use the public GET
``/spolki`` / ``/spolki?limit=403`` endpoints instead. No paid GPW data
product is used and no WIG20/WIG30 hand-written seed is shipped.

The cache is breadth only and never flows into information_items / Today
feed. Each entry stores ticker/name/ISIN/board under the normalized PL
ticker so future disclosure/news slices can align by ISIN/name.
"""

from __future__ import annotations

from html.parser import HTMLParser
import json
import logging
import os
import re
import ssl
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Mapping, Optional
from urllib.request import HTTPSHandler, Request, build_opener, urlopen

from ..web_repository import normalize_pl_ticker

LOGGER = logging.getLogger(__name__)

DEFAULT_CACHE_PATH = ".cache/investment_monitor/pl_universe.json"
DIRECTORY_URL = "https://www.gpw.pl/spolki?limit=403"
NEWCONNECT_URL = "https://newconnect.pl/spolki?limit=403"
DIRECTORY_URL_ENV = "PL_UNIVERSE_DIRECTORY_URL"
NEWCONNECT_URL_ENV = "PL_UNIVERSE_NEWCONNECT_URL"
DEFAULT_USER_AGENT = "InvestmentMonitor/0.1 (internal workspace)"

_BOARD_LABELS = {
    "G\u0142\u00f3wny Rynek": "GPW Main Market",
}


class PlUniverseError(RuntimeError):
    """Raised when the PL universe cannot be refreshed at all."""


def load_pl_universe(
    path: Optional[Path] = None,
) -> Optional[Mapping[str, Any]]:
    """Load a cached PL universe payload, or None when absent/invalid."""
    cache_path = _cache_path(path)
    try:
        with cache_path.open("r", encoding="utf-8") as cache_file:
            return json.load(cache_file)
    except (OSError, json.JSONDecodeError):
        return None


def refresh_pl_universe(
    *,
    path: Optional[Path] = None,
    opener: Optional[Callable[..., Any]] = None,
    directory_url: Optional[str] = None,
    newconnect_url: Optional[str] = None,
    refreshed_at: Optional[str] = None,
) -> Mapping[str, Any]:
    """Refresh the PL universe from the two GPW HTML directories.

    Each board source is fetched independently; a single source failure is
    logged and does not discard the other board. Only when every source
    fails is ``PlUniverseError`` raised. The cache is written atomically
    (tmp + replace) and is breadth only (never information_items).
    """
    cache_path = _cache_path(path)
    verify_ssl = (
        os.environ.get("PL_UNIVERSE_VERIFY_SSL", "true")
        .strip()
        .lower()
    ) not in {"0", "false", "no", "off"}
    default_opener = _make_opener(verify_ssl)
    active_opener = opener or default_opener
    main = directory_url or os.environ.get(
        DIRECTORY_URL_ENV, DIRECTORY_URL
    )
    newconnect = newconnect_url or os.environ.get(
        NEWCONNECT_URL_ENV, NEWCONNECT_URL
    )

    entries: Dict[str, Mapping[str, Any]] = {}
    counts: Dict[str, int] = {}
    sources: List[str] = []
    failures: List[str] = []
    for label, url, board in (
        ("gpw_spolki_html", main, "GPW Main Market"),
        ("newconnect_spolki_html", newconnect, "NewConnect"),
    ):
        try:
            rows = _fetch_directory_rows(url, active_opener)
        except Exception as error:
            message = str(error) or error.__class__.__name__
            failures.append(f"{label}: {message}")
            LOGGER.warning("pl_universe source=%s failed: %s", label, error)
            continue
        sources.append(label)
        for row in rows:
            ticker = str(row.get("ticker") or "").strip()
            if not ticker or ticker in entries:
                continue
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
        raise PlUniverseError(
            "PL universe sources failed; no GPW/NewConnect entries "
            f"available ({'; '.join(failures) or 'no sources wired'})."
        )

    payload = {
        "updated_at": (
            refreshed_at or datetime.now(timezone.utc).isoformat()
        ),
        "source": sources,
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


def pl_universe_name_map(
    path: Optional[Path] = None,
) -> Mapping[str, Mapping[str, str]]:
    """Return normalized ticker -> {name, exchange, board, isin}."""
    payload = load_pl_universe(path)
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
            or "GPW Main Market"
        )
        result[ticker] = {
            "name": str(item.get("name") or ticker),
            "exchange": board,
            "board": board,
            "isin": str(item.get("isin") or ""),
        }
    return result


def search_pl_universe(
    query: str,
    path: Optional[Path] = None,
) -> List[Mapping[str, Any]]:
    """Search the cached PL universe by ticker, name, ISIN or board."""
    payload = load_pl_universe(path)
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


class _DirectoryTableParser(HTMLParser):
    """Extract company rows from a GPW/NewConnect directory table."""

    def __init__(self) -> None:
        super().__init__()
        self.rows: List[Mapping[str, str]] = []
        self._in_tbody = False
        self._in_row = False
        self._row: Dict[str, str] = {}
        self._capture: Optional[str] = None
        self._text: List[str] = []

    def handle_starttag(
        self,
        tag: str,
        attrs: List[tuple],
    ) -> None:
        attributes = dict(attrs)
        if tag == "tbody" and attributes.get("id") == "search-result":
            self._in_tbody = True
            return
        if not self._in_tbody:
            return
        if tag == "tr":
            self._in_row = True
            self._row = {}
            return
        if not self._in_row:
            return
        if tag == "a":
            match = re.search(
                r"spolka\?isin=([A-Z0-9]+)",
                str(attributes.get("href") or ""),
            )
            if match:
                self._row["isin"] = match.group(1)
            return
        classes = str(attributes.get("class") or "").split()
        if tag == "strong" and "name" in classes:
            self._capture = "name"
            self._text = []
            return
        if tag == "small" and "grey" in classes:
            self._capture = "board"
            self._text = []

    def handle_endtag(self, tag: str) -> None:
        if tag == "tbody":
            self._in_tbody = False
            return
        if tag == "tr" and self._in_row:
            self.rows.append(self._row)
            self._in_row = False
            self._row = {}
            return
        if tag in ("strong", "small") and self._capture:
            self._row[self._capture] = " ".join(
                "".join(self._text).split()
            )
            self._capture = None
            self._text = []

    def handle_data(self, data: str) -> None:
        if self._capture:
            self._text.append(data)


def _fetch_directory_rows(
    url: str,
    opener: Callable[..., Any],
) -> List[Mapping[str, Any]]:
    request = Request(
        url,
        headers={
            "User-Agent": DEFAULT_USER_AGENT,
            "Accept": "text/html,*/*",
            "Accept-Language": "pl,en;q=0.8",
        },
        method="GET",
    )
    with opener(request, timeout=60) as response:
        raw = response.read()
    html = raw.decode("utf-8", errors="replace")
    parser = _DirectoryTableParser()
    parser.feed(html)

    records: List[Mapping[str, Any]] = []
    for row in parser.rows:
        name = str(row.get("name") or "").strip()
        ticker_match = re.search(r"\(([^)]+)\)\s*$", name)
        if not ticker_match:
            continue
        ticker = normalize_pl_ticker(ticker_match.group(1))
        if not ticker:
            continue
        clean_name = re.sub(r"\s*\([^)]*\)\s*$", "", name).strip()
        board_text = str(row.get("board") or "").split("|", 1)[0].strip()
        records.append(
            {
                "ticker": ticker,
                "name": clean_name or ticker,
                "isin": str(row.get("isin") or "").strip(),
                "board_text": _BOARD_LABELS.get(board_text, board_text),
            }
        )
    if not records:
        raise PlUniverseError(
            "GPW directory page returned no parseable company rows."
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
        path or os.environ.get("PL_UNIVERSE_CACHE_PATH", DEFAULT_CACHE_PATH)
    )
