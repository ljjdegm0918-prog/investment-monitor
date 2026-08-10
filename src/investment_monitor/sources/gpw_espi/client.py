"""GPW ESPI/EBI report list client (official GPW reports page).

Recon (live verified 2026-08-10): the official GPW "Raporty Sp\u00f3\u0142ek
ESPI/EBI" page (``https://www.gpw.pl/komunikaty``) is a server-rendered
HTML list. It supports key-free GET filtering by ISIN/company text and
pagination:

* ``?searchText=PLPKO0000016&limit=100&offset=0`` returns ESPI/EBI report
  rows for that issuer only (verified: 100 rows, all ``PLPKO0000016``).
* Each row carries a Warsaw timestamp, report type/number (ESPI/EBI),
  issuer name + ISIN, report title, and a deep link
  ``komunikat?geru_id=...&title=...`` to the full report page (which also
  exposes the attachment PDF path).

This is official GPW data, key-free, and does not use the paid GPW data
products or the ``espi.gpw.pl`` portal (which is unreachable from this
network with a TLS EOF). The page/HTML is a public web surface and may
change without notice, so parse failures raise a data error instead of
fake success. Matching is by ISIN (from the PL universe cache) because
the list shows issuer names/ISINs, not ticker mnemonics.
"""

from __future__ import annotations

from html.parser import HTMLParser
import html
import logging
import os
import re
import threading
import time
from datetime import date, datetime, timezone
from typing import Any, Callable, Dict, List, Mapping, Optional
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urljoin
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

LOGGER = logging.getLogger(__name__)

DEFAULT_BASE_URL = "https://www.gpw.pl/komunikaty"
DEFAULT_PUBLIC_BASE = "https://www.gpw.pl/"
RETRYABLE_STATUS_CODES = frozenset({429, 500, 502, 503, 504})
WARSAW = ZoneInfo("Europe/Warsaw")


class GpwEspiError(Exception):
    """Base error for GPW ESPI/EBI report collection."""


class GpwEspiRequestError(GpwEspiError):
    """Raised when the GPW request cannot be completed."""


class GpwEspiDataError(GpwEspiError):
    """Raised when the GPW page returns an unexpected shape."""


class GpwEspiClient:
    """Small stdlib HTML client for the official GPW ESPI/EBI list."""

    def __init__(
        self,
        base_url: str = DEFAULT_BASE_URL,
        public_base: str = DEFAULT_PUBLIC_BASE,
        timeout: float = 20.0,
        max_retries: int = 1,
        requests_per_second: float = 1.0,
        user_agent: str = "InvestmentMonitor/0.1 (internal workspace)",
        opener: Callable[..., Any] = urlopen,
        clock: Callable[[], float] = time.monotonic,
        sleeper: Callable[[float], None] = time.sleep,
    ) -> None:
        if not base_url.strip():
            raise ValueError("GPW ESPI base URL must not be empty.")
        if timeout <= 0:
            raise ValueError("GPW ESPI timeout must be greater than zero.")
        if max_retries < 0:
            raise ValueError("GPW ESPI max_retries must not be negative.")
        if requests_per_second <= 0:
            raise ValueError(
                "GPW ESPI requests_per_second must be greater than zero."
            )
        self._base_url = base_url.rstrip("/")
        self._public_base = public_base.rstrip("/") + "/"
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
    def from_environment(cls) -> "GpwEspiClient":
        return cls(
            base_url=os.environ.get("GPW_ESPI_URL", DEFAULT_BASE_URL),
            timeout=_read_float_environment(
                "GPW_ESPI_TIMEOUT_SECONDS", 20.0
            ),
            max_retries=_read_int_environment(
                "GPW_ESPI_MAX_RETRIES", 1
            ),
            requests_per_second=_read_float_environment(
                "GPW_ESPI_REQUESTS_PER_SECOND", 1.0
            ),
        )

    def fetch_reports(
        self,
        isin: str,
        start_date: date,
        end_date: date,
        *,
        page_size: int = 100,
        max_pages: int = 8,
    ) -> List[Mapping[str, Any]]:
        """Fetch ESPI/EBI report rows for one issuer ISIN within the window."""
        records: List[Mapping[str, Any]] = []
        offset = 0
        for _ in range(max_pages):
            url = (
                f"{self._base_url}?searchText={quote(isin)}"
                f"&limit={page_size}&offset={offset}"
            )
            body = self._get_html(url)
            page_records = _parse_page(body, self._public_base)
            records.extend(page_records)
            if len(page_records) < page_size:
                break
            offset += page_size
        return _filter_window(records, start_date, end_date)

    def _get_html(self, url: str) -> bytes:
        for attempt in range(self._max_retries + 1):
            self._wait_for_rate_limit()
            request = Request(
                url,
                headers={
                    "User-Agent": self._user_agent,
                    "Accept-Language": "pl,en;q=0.8",
                    "Accept": "text/html,*/*;q=0.8",
                },
                method="GET",
            )
            try:
                with self._opener(request, timeout=self._timeout) as response:
                    return response.read()
            except HTTPError as error:
                if (
                    error.code not in RETRYABLE_STATUS_CODES
                    or attempt == self._max_retries
                ):
                    raise GpwEspiRequestError(
                        f"GPW ESPI request failed with HTTP "
                        f"{error.code}: {url}"
                    ) from error
            except URLError as error:
                if attempt == self._max_retries:
                    raise GpwEspiRequestError(
                        f"GPW ESPI request failed after "
                        f"{self._max_retries + 1} attempts: {url}"
                    ) from error
            except TimeoutError as error:
                if attempt == self._max_retries:
                    raise GpwEspiRequestError(
                        f"GPW ESPI request timed out after "
                        f"{self._max_retries + 1} attempts: {url}"
                    ) from error
            self._sleeper(0.5 * (2**attempt))
        raise GpwEspiRequestError(f"GPW ESPI request failed: {url}")

    def _wait_for_rate_limit(self) -> None:
        with self._rate_limit_lock:
            now = self._clock()
            if self._last_request_at is not None:
                remaining = (
                    self._minimum_interval - (now - self._last_request_at)
                )
                if remaining > 0:
                    self._sleeper(remaining)
                    now = self._clock()
            self._last_request_at = now


class _ReportListParser(HTMLParser):
    """Extract ESPI/EBI report rows from the GPW ``komunikaty`` list."""

    def __init__(self, public_base: str) -> None:
        super().__init__()
        self.public_base = public_base
        self.rows: List[Dict[str, str]] = []
        self.saw_list = False
        self._in_list = False
        self._in_item = False
        self._item: Dict[str, str] = {}
        self._capture: Optional[str] = None
        self._text: List[str] = []

    def handle_starttag(
        self,
        tag: str,
        attrs: List[tuple],
    ) -> None:
        attributes = dict(attrs)
        classes = str(attributes.get("class") or "").split()
        if tag == "ul" and "list" in classes and attributes.get("id") == "search-result":
            self._in_list = True
            self.saw_list = True
            return
        if not self._in_list:
            return
        if tag == "li":
            self._in_item = True
            self._item = {}
            return
        if not self._in_item:
            return
        if tag == "a":
            href = str(attributes.get("href") or "")
            if href.startswith("komunikat?geru_id="):
                self._item["url"] = urljoin(self.public_base, html.unescape(href))
            return
        if tag == "span" and "date" in classes:
            self._capture = "date"
            self._text = []
            return
        if tag == "strong" and "name" in classes:
            self._capture = "name"
            self._text = []
            return
        if tag == "p":
            self._capture = "title"
            self._text = []

    def handle_endtag(self, tag: str) -> None:
        if tag == "ul":
            self._in_list = False
            return
        if tag == "li" and self._in_item:
            self.rows.append(self._item)
            self._in_item = False
            self._item = {}
            return
        if tag in ("span", "strong", "p") and self._capture:
            self._item[self._capture] = " ".join(
                "".join(self._text).split()
            )
            self._capture = None
            self._text = []

    def handle_data(self, data: str) -> None:
        if self._capture:
            self._text.append(data)


def _parse_page(
    body: bytes,
    public_base: str,
) -> List[Mapping[str, Any]]:
    try:
        document = body.decode("utf-8", errors="replace")
    except Exception as error:
        raise GpwEspiDataError(
            "GPW ESPI page could not be decoded."
        ) from error
    parser = _ReportListParser(public_base)
    parser.feed(document)
    if not parser.saw_list:
        raise GpwEspiDataError(
            "GPW ESPI page has no report list (page shape changed?)."
        )

    records: List[Mapping[str, Any]] = []
    for row in parser.rows:
        date_line = str(row.get("date") or "")
        match = re.match(
            r"^(\d{2})-(\d{2})-(\d{4}) "
            r"(\d{2}):(\d{2}):(\d{2})\s*\|(.*)$",
            date_line,
        )
        if not match:
            continue
        day, month, year, hour, minute, second = (
            int(match.group(1)),
            int(match.group(2)),
            int(match.group(3)),
            int(match.group(4)),
            int(match.group(5)),
            int(match.group(6)),
        )
        published_warsaw = datetime(
            year,
            month,
            day,
            hour,
            minute,
            second,
            tzinfo=WARSAW,
        )
        detail_parts = [
            part.strip()
            for part in match.group(7).split("|")
            if part.strip()
        ]
        report_type = detail_parts[1] if len(detail_parts) >= 2 else ""
        report_number = detail_parts[2] if len(detail_parts) >= 3 else ""
        name_text = str(row.get("name") or "").strip()
        isin_match = re.search(r"\(([A-Z0-9]{12})\)\s*$", name_text)
        company_name = (
            re.sub(r"\s*\([^)]*\)\s*$", "", name_text).strip()
            if isin_match
            else name_text
        )
        isin = isin_match.group(1) if isin_match else ""
        geru_match = re.search(r"geru_id=(\d+)", str(row.get("url") or ""))
        if not geru_match:
            continue
        title = str(row.get("title") or "").strip()
        if not title:
            continue
        records.append(
            {
                "external_id": geru_match.group(1),
                "title": title,
                "url": str(row.get("url") or ""),
                "published": published_warsaw.astimezone(timezone.utc),
                "company_name": company_name,
                "isin": isin,
                "report_type": report_type,
                "report_number": report_number,
            }
        )
    return records


def _filter_window(
    records: List[Mapping[str, Any]],
    start_date: date,
    end_date: date,
) -> List[Mapping[str, Any]]:
    kept: List[Mapping[str, Any]] = []
    for record in records:
        published = record["published"]
        warsaw_day = published.astimezone(WARSAW).date()
        if start_date <= warsaw_day <= end_date:
            kept.append(record)
    return kept


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
