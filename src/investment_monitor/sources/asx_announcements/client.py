"""ASX company-announcement archive client.

The current ASX quote-site API only exposes the newest five announcements per
company.  This client deliberately uses ASX's public *Historical market
announcements* search instead.  The first-party archive accepts a company
code and a calendar year (1998 onwards), renders the full result set for that
year, and supplies an ``idsId``-addressable official PDF for every result.

Using one request per calendar year makes a requested date window exact while
avoiding an undocumented five-record ceiling.  The archive is HTML rather than
a versioned API, so unexpected pages are surfaced as data errors instead of
being treated as an empty collection.
"""

from __future__ import annotations

import logging
import os
import re
import threading
import time
from datetime import date, datetime
from html.parser import HTMLParser
from typing import Any, Callable, List, Mapping, Optional, cast
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, urlencode, urljoin, urlparse
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

LOGGER = logging.getLogger(__name__)

DEFAULT_BASE_URL = "https://www.asx.com.au/asx/v2/statistics/announcements.do"
ASX_ORIGIN = "https://www.asx.com.au"
ASX_TIMEZONE = ZoneInfo("Australia/Sydney")
RETRYABLE_STATUS_CODES = frozenset({429, 500, 502, 503, 504})
_DATE_TIME_PATTERN = re.compile(
    r"(?P<date>\d{2}/\d{2}/\d{4})\s+(?P<time>\d{1,2}:\d{2}\s*[ap]m)",
    re.IGNORECASE,
)
_PAGE_COUNT_PATTERN = re.compile(r"\b(\d+)\s+pages?\b", re.IGNORECASE)
_FILE_SIZE_PATTERN = re.compile(
    r"\b([\d.]+\s*(?:KB|MB|GB))\b", re.IGNORECASE
)


class AsxAnnouncementsError(Exception):
    """Base error for ASX announcements collection."""


class AsxAnnouncementsRequestError(AsxAnnouncementsError):
    """Raised when the ASX request cannot be completed."""


class AsxAnnouncementsDataError(AsxAnnouncementsError):
    """Raised when ASX returns an unexpected payload."""


class AsxAnnouncementsClient:
    """Small stdlib client for ASX's first-party historical archive."""

    def __init__(
        self,
        base_url: str = DEFAULT_BASE_URL,
        timeout: float = 20.0,
        max_retries: int = 1,
        requests_per_second: float = 1.0,
        user_agent: str = "InvestmentMonitor/0.1 (internal workspace)",
        opener: Callable[..., Any] = urlopen,
        clock: Callable[[], float] = time.monotonic,
        sleeper: Callable[[float], None] = time.sleep,
    ) -> None:
        if not base_url.strip():
            raise ValueError("ASX announcements base URL must not be empty.")
        if timeout <= 0:
            raise ValueError(
                "ASX announcements timeout must be greater than zero."
            )
        if max_retries < 0:
            raise ValueError(
                "ASX announcements max_retries must not be negative."
            )
        if requests_per_second <= 0:
            raise ValueError(
                "ASX announcements requests_per_second must be greater "
                "than zero."
            )
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout
        self._max_retries = max_retries
        self._minimum_interval = 1.0 / requests_per_second
        self._user_agent = user_agent
        self._opener = opener
        self._clock = clock
        self._sleeper = sleeper
        self._last_request_at: Optional[float] = None
        self._rate_limit_lock = threading.Lock()

    @classmethod
    def from_environment(cls) -> "AsxAnnouncementsClient":
        return cls(
            base_url=os.environ.get(
                "ASX_ANNOUNCEMENTS_URL",
                DEFAULT_BASE_URL,
            ),
            timeout=_read_float_environment(
                "ASX_ANNOUNCEMENTS_TIMEOUT_SECONDS",
                20.0,
            ),
            max_retries=_read_int_environment(
                "ASX_ANNOUNCEMENTS_MAX_RETRIES",
                1,
            ),
            requests_per_second=_read_float_environment(
                "ASX_ANNOUNCEMENTS_REQUESTS_PER_SECOND",
                1.0,
            ),
        )

    def fetch_announcements(
        self,
        code: str,
        start_date: date,
        end_date: date,
    ) -> List[Mapping[str, Any]]:
        """Fetch the exact ASX archive window, split by calendar year."""
        if end_date < start_date:
            raise ValueError("ASX announcement end_date must not precede start_date.")
        if start_date.year < 1998:
            raise AsxAnnouncementsDataError(
                "ASX public historical archive coverage begins in 1998."
            )
        records: List[Mapping[str, Any]] = []
        for year in range(start_date.year, end_date.year + 1):
            list_url = self._archive_url(code, year)
            records.extend(
                _parse_archive_page(
                    self._get_text(list_url),
                    list_url=list_url,
                    start_date=start_date,
                    end_date=end_date,
                )
            )
        return records

    def _archive_url(self, code: str, year: int) -> str:
        query = urlencode(
            {
                "asxCode": code.upper(),
                "by": "asxCode",
                "timeframe": "Y",
                "year": year,
            }
        )
        return f"{self._base_url}?{query}"

    def _get_text(self, url: str) -> str:
        for attempt in range(self._max_retries + 1):
            self._wait_for_rate_limit()
            request = Request(
                url,
                headers={
                    "User-Agent": self._user_agent,
                    "Accept": "text/html,application/xhtml+xml",
                    "Accept-Language": "en-AU,en;q=0.9",
                },
                method="GET",
            )
            try:
                with self._opener(request, timeout=self._timeout) as response:
                    raw = cast(bytes, response.read())
                return raw.decode("utf-8", errors="replace")
            except HTTPError as error:
                if (
                    error.code not in RETRYABLE_STATUS_CODES
                    or attempt == self._max_retries
                ):
                    raise AsxAnnouncementsRequestError(
                        f"ASX announcements request failed with HTTP "
                        f"{error.code}: {url}"
                    ) from error
            except URLError as error:
                if attempt == self._max_retries:
                    raise AsxAnnouncementsRequestError(
                        f"ASX announcements request failed after "
                        f"{self._max_retries + 1} attempts: {url}"
                    ) from error
            except TimeoutError as error:
                if attempt == self._max_retries:
                    raise AsxAnnouncementsRequestError(
                        f"ASX announcements request timed out after "
                        f"{self._max_retries + 1} attempts: {url}"
                    ) from error
            self._sleeper(0.5 * (2**attempt))
        raise AsxAnnouncementsRequestError(
            f"ASX announcements request failed: {url}"
        )

    def _wait_for_rate_limit(self) -> None:
        with self._rate_limit_lock:
            now = self._clock()
            if self._last_request_at is not None:
                remaining = self._minimum_interval - (
                    now - self._last_request_at
                )
                if remaining > 0:
                    self._sleeper(remaining)
                    now = self._clock()
            self._last_request_at = now


class _ArchiveParser(HTMLParser):
    """Extract only result-table rows from the ASX archive HTML."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.rows: List[List[dict[str, Any]]] = []
        self._cells: List[dict[str, Any]] = []
        self._in_row = False
        self._cell_depth = 0

    def handle_starttag(
        self,
        tag: str,
        attrs: List[tuple[str, Optional[str]]],
    ) -> None:
        attributes = dict(attrs)
        if tag == "tr":
            self._in_row = True
            self._cells = []
        elif self._in_row and tag == "td":
            self._cell_depth += 1
            if self._cell_depth == 1:
                self._cells.append({"text": [], "href": "", "price": False})
        elif self._in_row and self._cell_depth and tag == "a" and self._cells:
            href = attributes.get("href")
            if href:
                self._cells[-1]["href"] = href
        elif self._in_row and self._cell_depth and tag == "img" and self._cells:
            if str(attributes.get("title") or "").lower() == "price sensitive":
                self._cells[-1]["price"] = True
        elif self._in_row and self._cell_depth and tag == "br" and self._cells:
            self._cells[-1]["text"].append(" ")
        elif self._in_row and self._cell_depth and tag == "span" and self._cells:
            self._cells[-1]["text"].append(" ")

    def handle_endtag(self, tag: str) -> None:
        if tag == "td" and self._in_row and self._cell_depth:
            self._cell_depth -= 1
        elif tag == "span" and self._in_row and self._cell_depth and self._cells:
            self._cells[-1]["text"].append(" ")
        elif tag == "tr" and self._in_row:
            self.rows.append(self._cells)
            self._cells = []
            self._cell_depth = 0
            self._in_row = False

    def handle_data(self, data: str) -> None:
        if self._in_row and self._cell_depth and self._cells:
            self._cells[-1]["text"].append(data)


def _parse_archive_page(
    html: str,
    *,
    list_url: str,
    start_date: date,
    end_date: date,
) -> List[Mapping[str, Any]]:
    parser = _ArchiveParser()
    parser.feed(html)
    parser.close()
    records: List[Mapping[str, Any]] = []
    archive_rows_seen = 0
    for cells in parser.rows:
        if len(cells) < 3:
            continue
        date_text = _normalise_text(cells[0]["text"])
        published = _parse_published(date_text)
        href = str(cells[2]["href"] or "")
        if published is None and "displayAnnouncement.do" not in href:
            continue
        archive_rows_seen += 1
        external_id = _announcement_id(href)
        title = _archive_title(cells[2]["text"])
        if (
            published is None
            or "displayAnnouncement.do" not in href
            or not external_id
            or not title
        ):
            raise AsxAnnouncementsDataError(
                "ASX announcement archive contained an unparseable result row."
            )
        if not start_date <= published.date() <= end_date:
            continue
        detail_url = urljoin(ASX_ORIGIN, href)
        detail_text = _normalise_text(cells[2]["text"])
        page_count = _first_match(_PAGE_COUNT_PATTERN, detail_text)
        file_size = _first_match(_FILE_SIZE_PATTERN, detail_text)
        records.append(
            {
                "external_id": external_id,
                "title": title,
                "published": published,
                "announcement_type": "announcement",
                "file_size": file_size or "",
                "page_count": int(page_count) if page_count else None,
                "is_price_sensitive": bool(cells[1]["price"]),
                "url": detail_url,
                "list_url": list_url,
            }
        )
    if archive_rows_seen or "No announcements were released" in html:
        return records
    raise AsxAnnouncementsDataError(
        "ASX announcements archive did not contain results or an explicit empty state."
    )


def _normalise_text(parts: List[str]) -> str:
    return " ".join("".join(parts).split())


def _parse_published(value: str) -> Optional[datetime]:
    match = _DATE_TIME_PATTERN.search(value)
    if match is None:
        return None
    try:
        naive = datetime.strptime(
            f"{match.group('date')} {match.group('time').upper()}",
            "%d/%m/%Y %I:%M %p",
        )
    except ValueError:
        return None
    return naive.replace(tzinfo=ASX_TIMEZONE)


def _announcement_id(href: str) -> str:
    ids = parse_qs(urlparse(href).query).get("idsId", [])
    return ids[0].strip() if ids else ""


def _archive_title(parts: List[str]) -> str:
    text = _normalise_text(parts)
    text = _PAGE_COUNT_PATTERN.sub("", text)
    text = _FILE_SIZE_PATTERN.sub("", text)
    return " ".join(text.split()).strip()


def _first_match(pattern: re.Pattern[str], value: str) -> Optional[str]:
    match = pattern.search(value)
    return match.group(1).replace(" ", "") if match else None


def _read_float_environment(name: str, default: float) -> float:
    value = os.environ.get(name)
    if value is None:
        return default
    try:
        return float(value)
    except ValueError as error:
        raise ValueError(f"{name} must be a number.") from error


def _read_int_environment(name: str, default: int) -> int:
    value = os.environ.get(name)
    if value is None:
        return default
    try:
        return int(value)
    except ValueError as error:
        raise ValueError(f"{name} must be an integer.") from error
