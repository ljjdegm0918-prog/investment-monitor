"""JPX official TSE ETF listed-issues universe.

The English JPX ``Listed Issues - ETFs`` page publishes one HTML table with
the current code, fund name, benchmark and management company.  This module
is intentionally ETF-only: it does not upgrade the broader Japanese stock
universe.  Parsing fails closed when JPX changes the required columns or
returns an empty table.
"""

from __future__ import annotations

from datetime import datetime, timezone
from html.parser import HTMLParser
import json
import os
from pathlib import Path
import re
from typing import Any, Callable, Dict, List, Mapping, Optional
from urllib.request import Request, urlopen

from ..sources.jp_news.symbols import normalize_jp_ticker

DEFAULT_CACHE_PATH = ".cache/investment_monitor/jp_etf_universe.json"
DIRECTORY_URL = "https://www.jpx.co.jp/english/equities/products/etfs/issues/01.html"
DIRECTORY_URL_ENV = "JP_ETF_UNIVERSE_DIRECTORY_URL"
DEFAULT_USER_AGENT = "InvestmentMonitor/0.1 (internal workspace)"
REQUIRED_HEADERS = (
    "Listing Date",
    "Index",
    "Code",
    "Fund Name",
    "Management Company",
)


class JpEtfUniverseError(RuntimeError):
    """Raised when the official JPX ETF directory cannot be refreshed."""


class _TableParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.tables: List[List[List[str]]] = []
        self._table_depth = 0
        self._rows: List[List[str]] = []
        self._row: Optional[List[str]] = None
        self._cell: Optional[List[str]] = None
        self._ignored_link_depth = 0

    def handle_starttag(self, tag: str, attrs: List[tuple[str, Optional[str]]]) -> None:
        attributes = dict(attrs)
        if tag == "a" and "inav-btn" in str(attributes.get("class") or "").split():
            self._ignored_link_depth += 1
        if tag == "table":
            self._table_depth += 1
            if self._table_depth == 1:
                self._rows = []
        elif self._table_depth == 1 and tag == "tr":
            self._row = []
        elif self._table_depth == 1 and tag in ("th", "td") and self._row is not None:
            self._cell = []

    def handle_data(self, data: str) -> None:
        if self._cell is not None and not self._ignored_link_depth:
            self._cell.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag == "a" and self._ignored_link_depth:
            self._ignored_link_depth -= 1
        if self._table_depth == 1 and tag in ("th", "td") and self._cell is not None:
            assert self._row is not None
            self._row.append(_clean_text(" ".join(self._cell)))
            self._cell = None
        elif self._table_depth == 1 and tag == "tr" and self._row is not None:
            if self._row:
                self._rows.append(self._row)
            self._row = None
        elif tag == "table" and self._table_depth:
            if self._table_depth == 1 and self._rows:
                self.tables.append(self._rows)
            self._table_depth -= 1


def _clean_text(value: str) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def parse_jp_etf_html(html: str) -> List[Mapping[str, str]]:
    """Parse the one JPX table whose first required columns match exactly."""
    parser = _TableParser()
    parser.feed(html)
    matching = [
        table for table in parser.tables
        if table and tuple(cell.strip() for cell in table[0][:5]) == REQUIRED_HEADERS
    ]
    if len(matching) != 1:
        raise JpEtfUniverseError("JPX ETF page required table changed or is ambiguous.")

    records: List[Mapping[str, str]] = []
    seen: set[str] = set()
    for row in matching[0][1:]:
        if len(row) < 5:
            raise JpEtfUniverseError("JPX ETF page contains a malformed data row.")
        listing_date, index_name, raw_code, fund_name, manager = row[:5]
        cleaned_code = _clean_text(raw_code).upper()
        if not re.fullmatch(r"(?:\d{4}|\d{3}[A-Z])", cleaned_code) or not fund_name:
            raise JpEtfUniverseError("JPX ETF page contains an invalid code or fund name.")
        code = normalize_jp_ticker(cleaned_code)
        if code in seen:
            raise JpEtfUniverseError(f"JPX ETF page contains duplicate code {code}.")
        seen.add(code)
        records.append({
            "ticker": code,
            "name": fund_name,
            "index": index_name,
            "management_company": manager,
            "listing_date": listing_date,
            "board": "TSE ETF",
            "exchange": "TSE",
            "instrument_type": "ETF",
            "status": "active",
        })
    if not records:
        raise JpEtfUniverseError("JPX ETF directory returned no instruments.")
    return sorted(records, key=lambda item: item["ticker"])


def load_jp_etf_universe(path: Optional[Path] = None) -> Optional[Mapping[str, Any]]:
    cache = Path(path or os.environ.get("JP_ETF_UNIVERSE_CACHE_PATH", DEFAULT_CACHE_PATH))
    try:
        payload = json.loads(cache.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) and isinstance(payload.get("items"), list) else None


def refresh_jp_etf_universe(
    *,
    path: Optional[Path] = None,
    opener: Callable[..., Any] = urlopen,
    url: Optional[str] = None,
    refreshed_at: Optional[str] = None,
) -> Mapping[str, Any]:
    source_url = url or os.environ.get(DIRECTORY_URL_ENV, DIRECTORY_URL)
    request = Request(source_url, headers={
        "User-Agent": DEFAULT_USER_AGENT,
        "Accept": "text/html,application/xhtml+xml",
        "Accept-Language": "en;q=1.0",
    })
    try:
        with opener(request, timeout=30) as response:
            html = response.read().decode("utf-8", errors="replace")
        items = parse_jp_etf_html(html)
    except JpEtfUniverseError:
        raise
    except Exception as error:
        raise JpEtfUniverseError(f"JPX ETF directory request failed: {error}") from error

    payload: Mapping[str, Any] = {
        "updated_at": refreshed_at or datetime.now(timezone.utc).isoformat(),
        "source": ["jpx_listed_issues_etfs"],
        "source_url": source_url,
        "counts_by_type": {"ETF": len(items)},
        "items": items,
    }
    cache = Path(path or os.environ.get("JP_ETF_UNIVERSE_CACHE_PATH", DEFAULT_CACHE_PATH))
    cache.parent.mkdir(parents=True, exist_ok=True)
    temporary = cache.with_suffix(cache.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    temporary.replace(cache)
    return payload


def jp_etf_universe_name_map(path: Optional[Path] = None) -> Mapping[str, Mapping[str, str]]:
    payload = load_jp_etf_universe(path)
    if not payload:
        return {}
    return {
        str(item["ticker"]): {
            "name": str(item.get("name") or item["ticker"]),
            "exchange": str(item.get("exchange") or "TSE"),
            "board": str(item.get("board") or "TSE ETF"),
            "instrument_type": "ETF",
        }
        for item in payload.get("items") or []
        if item.get("ticker")
    }


def search_jp_etf_universe(query: str, path: Optional[Path] = None) -> List[Mapping[str, Any]]:
    payload = load_jp_etf_universe(path)
    needle = _clean_text(query).lower()
    if not payload or not needle:
        return []
    matches = []
    for item in payload.get("items") or []:
        haystack = " ".join(str(item.get(key) or "") for key in (
            "ticker", "name", "index", "management_company"
        )).lower()
        if needle in haystack:
            matches.append(dict(item))
        if len(matches) >= 50:
            break
    return matches


__all__ = [
    "JpEtfUniverseError",
    "jp_etf_universe_name_map",
    "load_jp_etf_universe",
    "parse_jp_etf_html",
    "refresh_jp_etf_universe",
    "search_jp_etf_universe",
]
