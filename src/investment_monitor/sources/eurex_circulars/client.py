"""Fail-closed HTML client for the official Eurex circular archive."""

from __future__ import annotations

from datetime import date, datetime
from html.parser import HTMLParser
import html
import re
from typing import Any, Callable, Dict, List, Mapping
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin
from urllib.request import Request, urlopen

BASE_URL = "https://www.eurex.com/ex-en/find/circulars/1720!search?hitsPerPage=50&sort=sDate%20desc"
PUBLIC_BASE = "https://www.eurex.com"


class EurexError(Exception):
    pass


class EurexRequestError(EurexError):
    pass


class EurexDataError(EurexError):
    pass


class EurexCircularsClient:
    def __init__(self, opener: Callable[..., Any] = urlopen, timeout: float = 20.0) -> None:
        self._opener = opener
        self._timeout = timeout

    def fetch(self, start_date: date, end_date: date, *, max_pages: int = 100) -> List[Mapping[str, Any]]:
        url = BASE_URL
        records: List[Mapping[str, Any]] = []
        visited = set()
        for _ in range(max_pages):
            if url in visited:
                raise EurexDataError("Eurex pagination loop detected")
            visited.add(url)
            body = self._get(url)
            parser = _Parser()
            parser.feed(body.decode("utf-8"))
            if not parser.saw_container or not parser.records:
                raise EurexDataError("Eurex circular result structure changed")
            page_records = [{**record, "retrieval_url": url} for record in parser.records]
            records.extend(record for record in page_records if start_date <= record["date"] <= end_date)
            if min(record["date"] for record in page_records) < start_date:
                return records
            if not parser.next_url:
                return records
            url = urljoin(PUBLIC_BASE, html.unescape(parser.next_url))
        raise EurexDataError(f"Eurex results exceed max_pages={max_pages}")

    def _get(self, url: str) -> bytes:
        request = Request(url, headers={"User-Agent": "InvestmentMonitor/0.1", "Accept": "text/html"})
        try:
            with self._opener(request, timeout=self._timeout) as response:
                return response.read()
        except HTTPError as error:
            raise EurexRequestError(f"Eurex request failed with HTTP {error.code}") from error
        except (URLError, TimeoutError) as error:
            raise EurexRequestError("Eurex request failed") from error


class _Parser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.records: List[Dict[str, Any]] = []
        self.next_url: str | None = None
        self.saw_container = False
        self._record: Dict[str, Any] | None = None
        self._capture: str | None = None
        self._text: List[str] = []

    def handle_starttag(self, tag: str, attrs: List[tuple]) -> None:
        attributes = dict(attrs)
        classes = str(attributes.get("class") or "").split()
        if tag == "div" and "hits-sl-content-container" in classes:
            self.saw_container = True
        if tag == "a" and "teasable-search-result-link" in classes:
            self._record = {"url": urljoin(PUBLIC_BASE, str(attributes.get("href") or ""))}
        elif self._record is not None and "search-result-date" in classes:
            self._capture, self._text = "date", []
        elif self._record is not None and "search-result-tagline" in classes:
            self._capture, self._text = "tagline", []
        elif self._record is not None and "search-result-description" in classes:
            self._capture, self._text = "title", []
        if tag == "button" and "pagination-button-next" in classes:
            self.next_url = str(attributes.get("data-js-search-link") or "") or None

    def handle_data(self, data: str) -> None:
        if self._capture:
            self._text.append(data)

    def handle_endtag(self, tag: str) -> None:
        if self._capture and tag in {"p", "h1", "h2"}:
            value = " ".join(" ".join(self._text).split())
            if self._capture == "date":
                match = re.search(r"Release date:\s*(.+)$", value)
                if not match:
                    raise EurexDataError("Eurex result date is missing")
                self._record["published_at_raw"] = match.group(1)
                self._record["date"] = datetime.strptime(match.group(1), "%b %d, %Y").date()
            else:
                self._record[self._capture] = value
            self._capture, self._text = None, []
        if tag == "a" and self._record is not None:
            required = {"url", "date", "title", "tagline"}
            if required.issubset(self._record):
                self._record["external_id"] = self._record["url"].rstrip("/").rsplit("-", 1)[-1]
                self._record["raw_payload"] = dict(self._record)
                self.records.append(self._record)
            self._record = None
