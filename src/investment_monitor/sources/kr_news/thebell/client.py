"""TheBell (더벨) stock news client.

Recon: guessed article-list endpoints returned soft 404 pages from the
current network, so the live URL could not be confirmed. The parser is
locked to a minimal fixture of TheBell's article-list markup
(``Article.asp?svccode=..&comp_id=..`` links plus a date cell); this
connector is registered disabled until a reachable stock news URL is
confirmed.
"""

from __future__ import annotations

import hashlib
import html as html_lib
import logging
import os
import re
import threading
import time
from datetime import date
from typing import Any, Callable, List, Mapping, Optional
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from ..common import DEFAULT_USER_AGENT, normalize_kr_ticker, parse_kst_datetime, strip_tags

LOGGER = logging.getLogger(__name__)

DEFAULT_BASE_URL = "http://www.thebell.co.kr"
RETRYABLE_STATUS_CODES = frozenset({429, 500, 502, 503, 504})


class TheBellError(Exception):
    """Base error for TheBell news collection."""


class TheBellRequestError(TheBellError):
    """Raised when the TheBell request cannot be completed."""


class TheBellDataError(TheBellError):
    """Raised when TheBell returns an unexpected page."""


class TheBellClient:
    def __init__(
        self,
        base_url: str = DEFAULT_BASE_URL,
        timeout: float = 15.0,
        max_retries: int = 1,
        requests_per_second: float = 2.0,
        user_agent: str = DEFAULT_USER_AGENT,
        opener: Callable[..., Any] = urlopen,
        clock: Callable[[], float] = time.monotonic,
        sleeper: Callable[[float], None] = time.sleep,
    ) -> None:
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
    def from_environment(cls) -> "TheBellClient":
        return cls(
            base_url=os.environ.get("THEBELL_BASE_URL", DEFAULT_BASE_URL),
            timeout=_read_float_environment("THEBELL_TIMEOUT_SECONDS", 15.0),
            max_retries=_read_int_environment("THEBELL_MAX_RETRIES", 1),
            requests_per_second=_read_float_environment(
                "THEBELL_REQUESTS_PER_SECOND",
                2.0,
            ),
        )

    def fetch_news(
        self,
        code: str,
        start_date: date,
        end_date: date,
    ) -> List[Mapping[str, Any]]:
        normalized = normalize_kr_ticker(code)
        url = (
            f"{self._base_url}/free/content/ArticleList.asp"
            f"?svccode=if&code={normalized}"
        )
        body = self._get_html(url)
        return _parse_article_html(
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
                    "Accept-Language": "ko-KR,ko;q=0.9,en;q=0.8",
                },
                method="GET",
            )
            try:
                with self._opener(request, timeout=self._timeout) as response:
                    raw = response.read()
                return raw.decode("euc-kr", errors="replace")
            except HTTPError as error:
                if (
                    error.code not in RETRYABLE_STATUS_CODES
                    or attempt == self._max_retries
                ):
                    raise TheBellRequestError(
                        f"TheBell request failed with HTTP {error.code}: {url}"
                    ) from error
            except URLError as error:
                if attempt == self._max_retries:
                    raise TheBellRequestError(
                        f"TheBell request failed after "
                        f"{self._max_retries + 1} attempts: {url}"
                    ) from error
            except TimeoutError as error:
                if attempt == self._max_retries:
                    raise TheBellRequestError(
                        f"TheBell request timed out after "
                        f"{self._max_retries + 1} attempts: {url}"
                    ) from error
            self._sleeper(0.5 * (2**attempt))
        raise TheBellRequestError(f"TheBell request failed: {url}")

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


def _parse_article_html(
    html: str,
    *,
    base_url: str,
    start_date: date,
    end_date: date,
) -> List[Mapping[str, Any]]:
    if "ArticleList" not in html and "Article.asp" not in html:
        raise TheBellDataError(
            "TheBell page did not contain the expected article list."
        )
    records: List[Mapping[str, Any]] = []
    for row in re.findall(r"<tr[^>]*>(.*?)</tr>", html, re.S):
        link = re.search(
            r'<a[^>]+href="([^"]*Article\.asp[^"]*)"[^>]*>(.*?)</a>',
            row,
            re.S,
        )
        if link is None:
            continue
        href, raw_title = link.groups()
        title = strip_tags(raw_title)
        if not title:
            continue
        href = html_lib.unescape(href)
        abs_url = (
            href if href.startswith("http") else f"{base_url}/{href.lstrip('/')}"
        )
        comp_id = ""
        query = href.split("?", 1)[-1]
        for pair in query.split("&"):
            if pair.startswith("comp_id="):
                comp_id = pair.split("=", 1)[1]
        external_id = (
            f"comp:{comp_id}" if comp_id else hashlib.sha1(abs_url.encode()).hexdigest()
        )
        cells = [
            strip_tags(cell)
            for cell in re.findall(r"<td[^>]*>(.*?)</td>", row, re.S)
        ]
        time_match = re.search(
            r"(20\d{2}[.\-/]\d{2}[.\-/]\d{2})",
            " ".join(cells),
        )
        published = (
            parse_kst_datetime(time_match.group(1))
            if time_match
            else None
        )
        if published is None:
            continue
        if not start_date <= published.date() <= end_date:
            continue
        records.append(
            {
                "external_id": external_id,
                "title": title,
                "published": published,
                "url": abs_url,
                "comp_id": comp_id,
            }
        )
    return records


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
