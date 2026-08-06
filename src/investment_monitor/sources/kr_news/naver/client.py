"""Naver Finance stock news list client.

Recon (verified live): the stock news list is an iframe rendered by
``GET https://finance.naver.com/item/news_news.naver?code=<code>``. Rows live
in ``table.type5`` with title links to ``/news_read.naver?office_id=..&
article_id=..`` (the page JS rewrites them to n.news.naver.com). The page is
EUC-KR. From the current network the list body is empty; the parser is
locked by fixtures and an empty message returns [].
"""

from __future__ import annotations

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

DEFAULT_BASE_URL = "https://finance.naver.com"
RETRYABLE_STATUS_CODES = frozenset({429, 500, 502, 503, 504})
DEFAULT_MAX_PAGES = 10


class NaverNewsError(Exception):
    """Base error for Naver Finance news collection."""


class NaverNewsRequestError(NaverNewsError):
    """Raised when the Naver request cannot be completed."""


class NaverNewsDataError(NaverNewsError):
    """Raised when Naver returns an unexpected page."""


class NaverNewsClient:
    """Small stdlib HTML client for the Naver Finance stock news list."""

    def __init__(
        self,
        base_url: str = DEFAULT_BASE_URL,
        timeout: float = 15.0,
        max_retries: int = 2,
        requests_per_second: float = 2.0,
        user_agent: str = DEFAULT_USER_AGENT,
        opener: Callable[..., Any] = urlopen,
        clock: Callable[[], float] = time.monotonic,
        sleeper: Callable[[float], None] = time.sleep,
        max_pages: int = DEFAULT_MAX_PAGES,
    ) -> None:
        if not base_url.strip():
            raise ValueError("Naver base URL must not be empty.")
        if timeout <= 0:
            raise ValueError("Naver timeout must be greater than zero.")
        if max_retries < 0:
            raise ValueError("Naver max_retries must not be negative.")
        if requests_per_second <= 0:
            raise ValueError(
                "Naver requests_per_second must be greater than zero."
            )
        if max_pages < 1:
            raise ValueError("Naver max_pages must be at least 1.")
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout
        self._max_retries = max_retries
        self._minimum_interval = 1.0 / requests_per_second
        self._user_agent = user_agent
        self._opener = opener
        self._clock = clock
        self._sleeper = sleeper
        self._max_pages = max_pages
        self._last_request_at: Optional[float] = None
        self._rate_limit_lock = threading.Lock()

    @classmethod
    def from_environment(cls) -> "NaverNewsClient":
        return cls(
            base_url=os.environ.get("NAVER_NEWS_BASE_URL", DEFAULT_BASE_URL),
            timeout=_read_float_environment("NAVER_NEWS_TIMEOUT_SECONDS", 15.0),
            max_retries=_read_int_environment("NAVER_NEWS_MAX_RETRIES", 2),
            requests_per_second=_read_float_environment(
                "NAVER_NEWS_REQUESTS_PER_SECOND",
                2.0,
            ),
            max_pages=_read_int_environment(
                "NAVER_NEWS_MAX_PAGES",
                DEFAULT_MAX_PAGES,
            ),
        )

    def fetch_news(
        self,
        code: str,
        start_date: date,
        end_date: date,
    ) -> List[Mapping[str, Any]]:
        """Fetch stock news for one KR code, paginating toward start_date.

        Pages are requested in order until one of: a page with no news /
        zero parseable rows, a page whose oldest row (before start-date
        truncation) is older than ``start_date``, or ``max_pages`` reached.
        Rows are window-filtered and deduplicated by (office_id,
        article_id), keeping the first occurrence.
        """
        normalized = normalize_kr_ticker(code)
        collected: List[Mapping[str, Any]] = []
        seen: set = set()
        for page in range(1, self._max_pages + 1):
            url = (
                f"{self._base_url}/item/news_news.naver"
                f"?code={normalized}&page={page}"
            )
            body = self._get_html(url, normalized)
            if _is_empty_news_page(body):
                break
            rows = _parse_news_rows(body)
            if not rows:
                break
            oldest = min(row["published"] for row in rows)
            reached_start = oldest.date() < start_date
            for row in rows:
                if start_date <= row["published"].date() <= end_date:
                    key = (str(row["office_id"]), str(row["article_id"]))
                    if key in seen:
                        continue
                    seen.add(key)
                    collected.append(row)
            if reached_start:
                break
            if page == self._max_pages:
                LOGGER.warning(
                    "naver_news code=%s reached max_pages=%d; "
                    "results may be incomplete",
                    normalized,
                    self._max_pages,
                )
        return collected

    def _get_html(self, url: str, code: str) -> str:
        for attempt in range(self._max_retries + 1):
            self._wait_for_rate_limit()
            request = Request(
                url,
                headers={
                    "User-Agent": self._user_agent,
                    "Accept-Language": "ko-KR,ko;q=0.9,en;q=0.8",
                    "Referer": (
                        f"{self._base_url}/item/main.naver?code={code}"
                    ),
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
                    raise NaverNewsRequestError(
                        f"Naver request failed with HTTP {error.code}: {url}"
                    ) from error
            except URLError as error:
                if attempt == self._max_retries:
                    raise NaverNewsRequestError(
                        f"Naver request failed after "
                        f"{self._max_retries + 1} attempts: {url}"
                    ) from error
            except TimeoutError as error:
                if attempt == self._max_retries:
                    raise NaverNewsRequestError(
                        f"Naver request timed out after "
                        f"{self._max_retries + 1} attempts: {url}"
                    ) from error
            self._sleeper(0.5 * (2**attempt))
        raise NaverNewsRequestError(f"Naver request failed: {url}")

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


def _parse_news_rows(html: str) -> List[Mapping[str, Any]]:
    """Parse every news row on one page without window filtering."""
    if "type5" not in html or "<tbody" not in html:
        raise NaverNewsDataError(
            "Naver stock news page did not contain the expected table."
        )
    records: List[Mapping[str, Any]] = []
    row_pattern = re.compile(r"<tr[^>]*>(.*?)</tr>", re.S)
    for row_html in row_pattern.findall(html):
        link = re.search(
            r"href=[\"'](/news_?[Rr]ead\.naver\?[^\"']+)[\"']",
            row_html,
        )
        if link is None:
            continue
        params = dict(
            re.findall(r"([a-zA-Z_]+)=([0-9]+)", link.group(1))
        )
        office_id = params.get("office_id") or params.get("officeId")
        article_id = params.get("article_id") or params.get("articleId")
        if not office_id or not article_id:
            continue
        title = _anchor_text(row_html)
        if not title:
            continue
        cells = [
            strip_tags(cell)
            for cell in re.findall(r"<td[^>]*>(.*?)</td>", row_html, re.S)
        ]
        provider = cells[1] if len(cells) > 1 else ""
        published = parse_kst_datetime(cells[2] if len(cells) > 2 else "")
        if published is None:
            continue
        records.append(
            {
                "office_id": office_id,
                "article_id": article_id,
                "title": title,
                "provider": provider,
                "published": published,
            }
        )
    return records


def _is_empty_news_page(html: str) -> bool:
    """True when Naver's 'no news' message is present.

    The empty page may lack the usual ``type5`` table, so this check must
    run before table parsing to stop pagination cleanly.
    """
    return "뉴스가 없습니다" in html


def _parse_news_html(
    html: str,
    *,
    start_date: date,
    end_date: date,
) -> List[Mapping[str, Any]]:
    if "뉴스가 없습니다" in html:
        return []
    return [
        row
        for row in _parse_news_rows(html)
        if start_date <= row["published"].date() <= end_date
    ]


def _anchor_text(row_html: str) -> str:
    anchor = re.search(
        r"<a[^>]*news_?[Rr]ead\.naver[^>]*>(.*?)</a>",
        row_html,
        re.S,
    )
    return strip_tags(anchor.group(1)) if anchor is not None else ""


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
