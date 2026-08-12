"""Google News RSS client for Eurex product queries.

Recon (verified live 2026-08-11): ``GET https://news.google.com/rss/search?
q=%22DAX%20Futures%22&hl=de&gl=DE&ceid=DE:de`` returns an RSS 2.0 feed
with DE-localised items (~71 items); the bare product code ``FDAX`` also
returns items (~19) but is more loosely related. The connector therefore
queries the product name from the EUX universe cache when available and
falls back to the Eurex product code otherwise. Key-free and stable;
results can be loosely related, so the honest "may be loosely related"
boundary is kept.
"""

from __future__ import annotations

import logging
import os
import threading
import time
from datetime import date
from typing import Any, Callable, List, Mapping, Optional
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen

from ...yahoo_common import (
    _parse_rss as _parse_rss_common,
    _read_float_environment,
    _read_int_environment,
)

LOGGER = logging.getLogger(__name__)

DEFAULT_BASE_URL = "https://news.google.com/rss/search"
RETRYABLE_STATUS_CODES = frozenset({429, 500, 502, 503, 504})


class GoogleEuxNewsError(Exception):
    """Base error for Google News EUX collection."""


class GoogleEuxNewsRequestError(GoogleEuxNewsError):
    """Raised when the Google News request cannot be completed."""


class GoogleEuxNewsDataError(GoogleEuxNewsError):
    """Raised when Google News returns an unexpected feed."""


class GoogleEuxNewsClient:
    """Small stdlib RSS client for Google News Eurex product queries."""

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
            raise ValueError("Google EUX news base URL must not be empty.")
        if timeout <= 0:
            raise ValueError("Google EUX news timeout must be greater than zero.")
        if max_retries < 0:
            raise ValueError("Google EUX news max_retries must not be negative.")
        if requests_per_second <= 0:
            raise ValueError(
                "Google EUX news requests_per_second must be greater than zero."
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
    def from_environment(cls) -> "GoogleEuxNewsClient":
        return cls(
            base_url=os.environ.get("GOOGLE_EUX_NEWS_URL", DEFAULT_BASE_URL),
            timeout=_read_float_environment(
                "GOOGLE_EUX_NEWS_TIMEOUT_SECONDS", 20.0
            ),
            max_retries=_read_int_environment(
                "GOOGLE_EUX_NEWS_MAX_RETRIES", 1
            ),
            requests_per_second=_read_float_environment(
                "GOOGLE_EUX_NEWS_REQUESTS_PER_SECOND", 1.0
            ),
        )

    def fetch_news(
        self,
        query: str,
        start_date: date,
        end_date: date,
    ) -> List[Mapping[str, Any]]:
        """Fetch and parse Google News RSS items for a product query."""
        url = (
            f"{self._base_url}?q={quote(query)}"
            "&hl=de&gl=DE&ceid=DE:de"
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
                    "Accept-Language": "de-DE,de,en;q=0.8",
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
                    raise GoogleEuxNewsRequestError(
                        f"Google EUX news request failed with HTTP "
                        f"{error.code}: {url}"
                    ) from error
            except URLError as error:
                if attempt == self._max_retries:
                    raise GoogleEuxNewsRequestError(
                        f"Google EUX news request failed after "
                        f"{self._max_retries + 1} attempts: {url}"
                    ) from error
            except TimeoutError as error:
                if attempt == self._max_retries:
                    raise GoogleEuxNewsRequestError(
                        f"Google EUX news request timed out after "
                        f"{self._max_retries + 1} attempts: {url}"
                    ) from error
            self._sleeper(0.5 * (2**attempt))
        raise GoogleEuxNewsRequestError(f"Google EUX news request failed: {url}")

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
    """Parse Google News RSS, raising the EUX data error on malformed XML."""
    return _parse_rss_common(
        body,
        start_date=start_date,
        end_date=end_date,
        data_error=GoogleEuxNewsDataError,
    )
