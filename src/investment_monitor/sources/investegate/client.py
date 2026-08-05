"""Investegate company announcement client.

Recon (verified live): ``GET https://www.investegate.co.uk/company/<TICKER>``
returns a static HTML table (``table-investegate``) with Date / Time /
Source / Announcement columns. Announcement links carry an RNS id as the
final path segment, e.g.
``https://www.investegate.co.uk/announcement/rns/vodafone-group--vod/.../9707019``.
This is an RNS-class public mirror, not an official LSEG feed; the page may
change without notice, so parsing failures raise a data error instead of
fake success.
"""

from __future__ import annotations

import hashlib
import logging
import os
import re
import threading
import time
from datetime import date, datetime, timezone
from typing import Any, Callable, List, Mapping, Optional
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

LOGGER = logging.getLogger(__name__)

DEFAULT_BASE_URL = "https://www.investegate.co.uk"
RETRYABLE_STATUS_CODES = frozenset({429, 500, 502, 503, 504})
LONDON = ZoneInfo("Europe/London")


class InvestegateError(Exception):
    """Base error for Investegate collection."""


class InvestegateRequestError(InvestegateError):
    """Raised when the Investegate request cannot be completed."""


class InvestegateDataError(InvestegateError):
    """Raised when Investegate returns an unexpected page."""


class InvestegateClient:
    """Small stdlib HTML client for the Investegate company page."""

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
            raise ValueError("Investegate base URL must not be empty.")
        if timeout <= 0:
            raise ValueError("Investegate timeout must be greater than zero.")
        if max_retries < 0:
            raise ValueError("Investegate max_retries must not be negative.")
        if requests_per_second <= 0:
            raise ValueError(
                "Investegate requests_per_second must be greater than zero."
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
    def from_environment(cls) -> "InvestegateClient":
        return cls(
            base_url=os.environ.get(
                "INVESTEGATE_BASE_URL",
                DEFAULT_BASE_URL,
            ),
            timeout=_read_float_environment(
                "INVESTEGATE_TIMEOUT_SECONDS",
                20.0,
            ),
            max_retries=_read_int_environment(
                "INVESTEGATE_MAX_RETRIES",
                1,
            ),
            requests_per_second=_read_float_environment(
                "INVESTEGATE_REQUESTS_PER_SECOND",
                1.0,
            ),
        )

    def fetch_announcements(
        self,
        ticker: str,
        start_date: date,
        end_date: date,
    ) -> List[Mapping[str, Any]]:
        """Fetch and parse the company announcement table."""
        code = ticker.strip().upper()
        url = f"{self._base_url}/company/{code}"
        body = self._get_html(url)
        return _parse_announcements(
            body,
            base_url=self._base_url,
            start_date=start_date,
            end_date=end_date,
        )

    def _get_html(self, url: str) -> str:
        for attempt in range(self._max_retries + 1):
            self._wait_for_rate_limit()
            request = Request(
                url,
                headers={
                    "User-Agent": self._user_agent,
                    "Accept-Language": "en-GB,en;q=0.9",
                    "Accept": "text/html,application/xhtml+xml,*/*;q=0.8",
                },
                method="GET",
            )
            try:
                with self._opener(request, timeout=self._timeout) as response:
                    raw = response.read()
                return raw.decode("utf-8", errors="replace")
            except HTTPError as error:
                if (
                    error.code not in RETRYABLE_STATUS_CODES
                    or attempt == self._max_retries
                ):
                    raise InvestegateRequestError(
                        f"Investegate request failed with HTTP "
                        f"{error.code}: {url}"
                    ) from error
            except URLError as error:
                if attempt == self._max_retries:
                    raise InvestegateRequestError(
                        f"Investegate request failed after "
                        f"{self._max_retries + 1} attempts: {url}"
                    ) from error
            except TimeoutError as error:
                if attempt == self._max_retries:
                    raise InvestegateRequestError(
                        f"Investegate request timed out after "
                        f"{self._max_retries + 1} attempts: {url}"
                    ) from error
            self._sleeper(0.5 * (2**attempt))
        raise InvestegateRequestError(f"Investegate request failed: {url}")

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


def _parse_announcements(
    html: str,
    *,
    base_url: str,
    start_date: date,
    end_date: date,
) -> List[Mapping[str, Any]]:
    if "table-investegate" not in html or "<tbody" not in html:
        raise InvestegateDataError(
            "Investegate page did not contain the announcement table."
        )
    records: List[Mapping[str, Any]] = []
    tbody_start = html.find("<tbody")
    tbody = html[tbody_start:]
    for row in re.findall(r"<tr[^>]*>(.*?)</tr>", tbody, re.S):
        link = re.search(
            r'<a[^>]+class="announcement-link"[^>]+href="'
            r"([^\"']+/)(\d+)\"[^>]*>(.*?)</a>",
            row,
            re.S,
        )
        if link is None:
            continue
        base_href, rns_id, raw_title = link.groups()
        title = re.sub(r"<[^>]+>", "", raw_title).strip()
        if not title:
            continue
        cells = [
            re.sub(r"<[^>]+>", " ", cell).strip()
            for cell in re.findall(r"<td[^>]*>(.*?)</td>", row, re.S)
        ]
        if len(cells) < 2:
            continue
        published = _parse_london_datetime(cells[0], cells[1])
        if published is None:
            continue
        if not start_date <= published.date() <= end_date:
            continue
        full_url = base_href + rns_id
        if not full_url.startswith("http"):
            full_url = f"{base_url}{full_url}"
        records.append(
            {
                "rns_id": rns_id,
                "title": title,
                "published": published,
                "url": full_url,
            }
        )
    return records


def _parse_london_datetime(
    date_text: str,
    time_text: str,
) -> Optional[datetime]:
    combined = f"{date_text} {time_text}".strip()
    try:
        naive = datetime.strptime(combined, "%d %b %Y %I:%M %p")
    except ValueError:
        return None
    return naive.replace(tzinfo=LONDON).astimezone(timezone.utc)


def stable_fallback_id(url: str) -> str:
    """Stable hash fallback when no RNS id is present."""
    return hashlib.sha1(url.encode("utf-8")).hexdigest()


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
