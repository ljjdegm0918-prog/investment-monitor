"""Yahoo Finance AT stock news RSS client.

Recon (verified live 2026-08-10): ``GET https://feeds.finance.yahoo.com/
rss/2.0/headline?s=PKO.VI&region=AT&lang=de-AT`` returns an RSS 2.0 feed
("Yahoo! Finance: PKO.VI News") with RFC822 pub dates.
``lang=en-US`` returns the same content when Yahoo localises it, so
identical titles are treated as a single-language result instead of fake
bilingual. Symbols need the ``.VI`` suffix at request time only; the stored
ticker stays the canonical root symbol. This is a key-free public RSS
mirror; may be loosely related and may break without notice, so parse
failures raise a data error instead of fake success.
"""

from __future__ import annotations

import logging
import os
import threading
import time
from datetime import date
from typing import Any, Callable, List, Mapping, Optional
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from ...yahoo_common import (
    _parse_rss as _parse_rss_common,
    _quote,
    _read_float_environment,
    _read_int_environment,
)

LOGGER = logging.getLogger(__name__)

DEFAULT_BASE_URL = "https://feeds.finance.yahoo.com/rss/2.0/headline"
RETRYABLE_STATUS_CODES = frozenset({429, 500, 502, 503, 504})


class YahooAtNewsError(Exception):
    """Base error for Yahoo Finance AT news collection."""


class YahooAtNewsRequestError(YahooAtNewsError):
    """Raised when the Yahoo request cannot be completed."""


class YahooAtNewsDataError(YahooAtNewsError):
    """Raised when Yahoo returns an unexpected feed."""


class YahooAtNewsClient:
    """Small stdlib RSS client for Yahoo Finance AT stock news."""

    def __init__(
        self,
        base_url: str = DEFAULT_BASE_URL,
        timeout: float = 8.0,
        max_retries: int = 1,
        requests_per_second: float = 1.0,
        user_agent: str = "InvestmentMonitor/0.1 (internal workspace)",
        opener: Callable[..., Any] = urlopen,
        clock: Callable[[], float] = time.monotonic,
        sleeper: Callable[[float], None] = time.sleep,
    ) -> None:
        if not base_url.strip():
            raise ValueError("Yahoo AT news base URL must not be empty.")
        if timeout <= 0:
            raise ValueError("Yahoo AT news timeout must be greater than zero.")
        if max_retries < 0:
            raise ValueError("Yahoo AT news max_retries must not be negative.")
        if requests_per_second <= 0:
            raise ValueError(
                "Yahoo AT news requests_per_second must be greater than zero."
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
    def from_environment(cls) -> "YahooAtNewsClient":
        return cls(
            base_url=os.environ.get("YAHOO_AT_NEWS_URL", DEFAULT_BASE_URL),
            timeout=_read_float_environment(
                "YAHOO_AT_NEWS_TIMEOUT_SECONDS", 8.0
            ),
            max_retries=_read_int_environment(
                "YAHOO_AT_NEWS_MAX_RETRIES", 1
            ),
            requests_per_second=_read_float_environment(
                "YAHOO_AT_NEWS_REQUESTS_PER_SECOND", 1.0
            ),
        )

    def fetch_news(
        self,
        symbol: str,
        start_date: date,
        end_date: date,
        lang: str = "de-AT",
    ) -> List[Mapping[str, Any]]:
        """Fetch and parse stock news for a Yahoo AT symbol (e.g. PKO.VI)."""
        url = (
            f"{self._base_url}?s={_quote(symbol)}"
            f"&region=AT&lang={_quote(lang)}"
        )
        body = self._get_xml(url)
        return _parse_rss(
            body,
            start_date=start_date,
            end_date=end_date,
        )

    def _get_xml(self, url: str) -> bytes:
        for attempt in range(self._max_retries + 1):
            self._wait_for_rate_limit()
            request = Request(
                url,
                headers={
                    "User-Agent": self._user_agent,
                    "Accept-Language": "de-AT,at,en;q=0.8",
                    "Accept": "application/rss+xml,application/xml,*/*;q=0.8",
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
                    raise YahooAtNewsRequestError(
                        f"Yahoo AT news request failed with HTTP "
                        f"{error.code}: {url}"
                    ) from error
            except URLError as error:
                if attempt == self._max_retries:
                    raise YahooAtNewsRequestError(
                        f"Yahoo AT news request failed after "
                        f"{self._max_retries + 1} attempts: {url}"
                    ) from error
            except TimeoutError as error:
                if attempt == self._max_retries:
                    raise YahooAtNewsRequestError(
                        f"Yahoo AT news request timed out after "
                        f"{self._max_retries + 1} attempts: {url}"
                    ) from error
            self._sleeper(0.5 * (2**attempt))
        raise YahooAtNewsRequestError(f"Yahoo AT news request failed: {url}")

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


def _parse_rss(
    body: bytes,
    *,
    start_date: date,
    end_date: date,
) -> List[Mapping[str, Any]]:
    """Parse a Yahoo RSS feed, raising the AT data error on malformed XML."""
    return _parse_rss_common(
        body,
        start_date=start_date,
        end_date=end_date,
        data_error=YahooAtNewsDataError,
    )
