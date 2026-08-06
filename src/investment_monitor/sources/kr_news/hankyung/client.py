"""Hankyung (한국경제) stock news client.

Recon: ``https://www.hankyung.com/stock/<code>`` returned HTTP 404 and the
site search returned HTTP 403 from the current network, so the live endpoint
could not be confirmed. The parser below is locked to a minimal fixture of
Hankyung's article-list markup (``/article/<id>`` links plus a date label);
this connector is registered disabled until a reachable stock news URL is
confirmed.
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

DEFAULT_BASE_URL = "https://www.hankyung.com"
RETRYABLE_STATUS_CODES = frozenset({429, 500, 502, 503, 504})


class HankyungError(Exception):
    """Base error for Hankyung news collection."""


class HankyungRequestError(HankyungError):
    """Raised when the Hankyung request cannot be completed."""


class HankyungDataError(HankyungError):
    """Raised when Hankyung returns an unexpected page."""


class HankyungClient:
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
    def from_environment(cls) -> "HankyungClient":
        return cls(
            base_url=os.environ.get("HANKYUNG_BASE_URL", DEFAULT_BASE_URL),
            timeout=_read_float_environment("HANKYUNG_TIMEOUT_SECONDS", 15.0),
            max_retries=_read_int_environment("HANKYUNG_MAX_RETRIES", 1),
            requests_per_second=_read_float_environment(
                "HANKYUNG_REQUESTS_PER_SECOND",
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
        url = f"{self._base_url}/stock/{normalized}"
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
                return raw.decode("utf-8", errors="replace")
            except HTTPError as error:
                if (
                    error.code not in RETRYABLE_STATUS_CODES
                    or attempt == self._max_retries
                ):
                    raise HankyungRequestError(
                        f"Hankyung request failed with HTTP {error.code}: {url}"
                    ) from error
            except URLError as error:
                if attempt == self._max_retries:
                    raise HankyungRequestError(
                        f"Hankyung request failed after "
                        f"{self._max_retries + 1} attempts: {url}"
                    ) from error
            except TimeoutError as error:
                if attempt == self._max_retries:
                    raise HankyungRequestError(
                        f"Hankyung request timed out after "
                        f"{self._max_retries + 1} attempts: {url}"
                    ) from error
            self._sleeper(0.5 * (2**attempt))
        raise HankyungRequestError(f"Hankyung request failed: {url}")

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
    if "article" not in html:
        raise HankyungDataError(
            "Hankyung page did not contain the expected article list."
        )
    records: List[Mapping[str, Any]] = []
    for block in re.findall(r'<div class="article">(.*?)</div>', html, re.S):
        link = re.search(
            r'<a[^>]+href="(/article/[0-9]+)"[^>]*>(.*?)</a>',
            block,
            re.S,
        )
        if link is None:
            continue
        href, raw_title = link.groups()
        title = strip_tags(raw_title)
        if not title:
            continue
        time_match = re.search(
            r"(20\d{2}[.\-/]\d{2}[.\-/]\d{2}(?:[ T]?\d{0,2}:?\d{0,2})?)",
            block,
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
                "article_path": href,
                "title": title,
                "published": published,
                "url": f"{base_url}{href}",
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
