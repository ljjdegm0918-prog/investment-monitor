"""Aquis (AQSE) tradeable universe cache (breadth only).

AQ-2 spike (2026-08-10): the official Aquis directory surfaces
(``embed.aquis.eu/companies`` and ``www.aquis.eu`` pages) sit behind a
Vercel bot challenge (HTTP 429, ``X-Vercel-Mitigated: challenge``) that
blocks stdlib/curl clients, and ``embed.aquis.eu/api/*`` returns the same
challenge. The only stable key-free AQSE directory reachable from stdlib
is the ticker.app mirror page ``https://www.ticker.app/aqse``, a
server-rendered HTML table with one row per instrument (name, TIDM badge
``AQSE:XXXX``, ISIN when published).

This is an **unofficial, partial mirror**: live on 2026-08-10 it contains
~79 unique AQSE instruments (61 with an ISIN; the official embed page
renders ~90 names, so completeness is not verified). It is deliberately
labelled as such and is never claimed to be the full AQSE universe. No
hand-written AQSE seed and no paid Aquis data product is shipped; LSE
FIRDS / UK directories are not filtered in as a substitute.

The cache is breadth only and never flows into information_items / Today
feed. Each entry stores ticker/name/ISIN/board under the normalized AQSE
ticker so future disclosure/news slices can align by ISIN/name.
"""

from __future__ import annotations

from html.parser import HTMLParser
import html
import json
import logging
import os
import re
import ssl
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Mapping, Optional
from urllib.request import HTTPSHandler, Request, build_opener, urlopen

from ..web_repository import normalize_aq_ticker

LOGGER = logging.getLogger(__name__)

DEFAULT_CACHE_PATH = ".cache/investment_monitor/aq_universe.json"
DIRECTORY_URL = "https://www.ticker.app/aqse"
DIRECTORY_URL_ENV = "AQ_UNIVERSE_DIRECTORY_URL"
DEFAULT_USER_AGENT = "InvestmentMonitor/0.1 (internal workspace)"
_ISIN_RE = re.compile(r"[A-Z]{2}[0-9A-Z]{10}")


class AqUniverseError(RuntimeError):
    """Raised when the AQ universe cannot be refreshed at all."""


def load_aq_universe(
    path: Optional[Path] = None,
) -> Optional[Mapping[str, Any]]:
    """Load a cached AQ universe payload, or None when absent/invalid."""
    cache_path = _cache_path(path)
    try:
        with cache_path.open("r", encoding="utf-8") as cache_file:
            return json.load(cache_file)
    except (OSError, json.JSONDecodeError):
        return None


def refresh_aq_universe(
    *,
    path: Optional[Path] = None,
    opener: Optional[Callable[..., Any]] = None,
    directory_url: Optional[str] = None,
    refreshed_at: Optional[str] = None,
) -> Mapping[str, Any]:
    """Refresh the AQ universe from the ticker.app AQSE mirror page.

    The official Aquis directory is not reachable from stdlib (Vercel
    challenge), so the single wired source is the key-free ticker.app
    AQSE HTML table. A parse/network failure raises ``AqUniverseError``
    (no second official board source exists). The cache is written
    atomically (tmp + replace) and is breadth only (never
    information_items). The source is an unofficial partial mirror and
    the payload records that boundary.
    """
    cache_path = _cache_path(path)
    verify_ssl = (
        os.environ.get("AQ_UNIVERSE_VERIFY_SSL", "true")
        .strip()
        .lower()
    ) not in {"0", "false", "no", "off"}
    default_opener = _make_opener(verify_ssl)
    active_opener = opener or default_opener
    url = directory_url or os.environ.get(DIRECTORY_URL_ENV, DIRECTORY_URL)

    try:
        rows = _fetch_directory_rows(url, active_opener)
    except Exception as error:
        message = str(error) or error.__class__.__name__
        raise AqUniverseError(
            "AQ universe refresh failed (ticker.app AQSE mirror): "
            f"{message}"
        ) from error

    entries: Dict[str, Mapping[str, Any]] = {}
    for row in rows:
        ticker = str(row.get("ticker") or "").strip()
        if not ticker or ticker in entries:
            continue
        entries[ticker] = {
            "ticker": ticker,
            "name": str(row.get("name") or ticker),
            "isin": str(row.get("isin") or ""),
            "board": "AQSE",
            "exchange": "AQSE",
            "status": "active",
            "source": "ticker_app_aqse_mirror",
        }

    if not entries:
        raise AqUniverseError(
            "AQ universe page returned no parseable company rows."
        )

    payload = {
        "updated_at": (
            refreshed_at or datetime.now(timezone.utc).isoformat()
        ),
        "source": ["ticker_app_aqse_html"],
        "counts": {"AQSE": len(entries)},
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


def aq_universe_name_map(
    path: Optional[Path] = None,
) -> Mapping[str, Mapping[str, str]]:
    """Return normalized ticker -> {name, exchange, board, isin}."""
    payload = load_aq_universe(path)
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
            or "AQSE"
        )
        result[ticker] = {
            "name": str(item.get("name") or ticker),
            "exchange": board,
            "board": board,
            "isin": str(item.get("isin") or ""),
        }
    return result


def search_aq_universe(
    query: str,
    path: Optional[Path] = None,
) -> List[Mapping[str, Any]]:
    """Search the cached AQ universe by ticker, name, ISIN or board."""
    payload = load_aq_universe(path)
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


class _TickerAppTableParser(HTMLParser):
    """Extract AQSE rows from the ticker.app directory page.

    A row is accepted only when it contains a TIDM badge with a
    ``title="AQSE:XXXX"`` attribute; rows without a badge (market widgets,
    unrelated tables) are ignored. The ISIN comes from the monospace
    cell when present; a 12-character ISIN pattern anywhere in the row is
    the fallback.
    """

    def __init__(self) -> None:
        super().__init__()
        self.rows: List[Mapping[str, str]] = []
        self._in_row = False
        self._row: Dict[str, str] = {}
        self._capture: Optional[str] = None
        self._text: List[str] = []
        self._td_capture: Optional[str] = None
        self._td_text: List[str] = []

    def handle_starttag(
        self,
        tag: str,
        attrs: List[tuple],
    ) -> None:
        attributes = dict(attrs)
        if tag == "tr":
            self._in_row = True
            self._row = {}
            return
        if not self._in_row:
            return
        if tag == "a":
            title = str(attributes.get("title") or "")
            href = str(attributes.get("href") or "")
            if title.startswith("AQSE:"):
                self._capture = "ticker"
                self._text = []
                return
            if href.startswith("/aqse/"):
                self._capture = "name"
                self._text = []
                return
        if tag == "td":
            classes = str(attributes.get("class") or "").split()
            if "font-mono" in classes:
                self._td_capture = "isin"
                self._td_text = []

    def handle_endtag(self, tag: str) -> None:
        if tag == "tr" and self._in_row:
            if self._row.get("ticker"):
                self.rows.append(self._row)
            self._in_row = False
            self._row = {}
            return
        if tag in ("a",) and self._capture:
            value = " ".join("".join(self._text).split())
            if value:
                self._row[self._capture] = html.unescape(value)
            self._capture = None
            self._text = []
            return
        if tag == "td" and self._td_capture:
            value = " ".join("".join(self._td_text).split())
            if value:
                self._row[self._td_capture] = html.unescape(value)
            self._td_capture = None
            self._td_text = []

    def handle_data(self, data: str) -> None:
        if self._capture:
            self._text.append(data)
        if self._td_capture:
            self._td_text.append(data)


def _fetch_directory_rows(
    url: str,
    opener: Callable[..., Any],
) -> List[Mapping[str, Any]]:
    request = Request(
        url,
        headers={
            "User-Agent": DEFAULT_USER_AGENT,
            "Accept": "text/html,*/*",
            "Accept-Language": "en-GB,en;q=0.8",
        },
        method="GET",
    )
    with opener(request, timeout=60) as response:
        raw = response.read()
    document = raw.decode("utf-8", errors="replace")
    parser = _TickerAppTableParser()
    parser.feed(document)

    records: List[Mapping[str, Any]] = []
    for row in parser.rows:
        ticker = normalize_aq_ticker(str(row.get("ticker") or ""))
        if not ticker:
            continue
        isin_match = _ISIN_RE.search(str(row.get("isin") or ""))
        records.append(
            {
                "ticker": ticker,
                "name": str(row.get("name") or ticker),
                "isin": isin_match.group(0) if isin_match else "",
            }
        )
    if not records:
        raise AqUniverseError(
            "ticker.app AQSE page returned no parseable company rows "
            "(page shape changed?)."
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
        path or os.environ.get("AQ_UNIVERSE_CACHE_PATH", DEFAULT_CACHE_PATH)
    )
