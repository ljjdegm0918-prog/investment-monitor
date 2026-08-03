"""HTTP communication for the SEC EDGAR source."""

from __future__ import annotations

import json
import os
import threading
import time
from typing import Any, Callable, Optional
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


class SECError(Exception):
    """Base exception for SEC collection errors."""


class SECConfigurationError(SECError):
    """Raised when required SEC configuration is missing or invalid."""


class SECRequestError(SECError):
    """Raised when an SEC HTTP request cannot be completed."""


class SECDataError(SECError):
    """Raised when SEC returns data in an unexpected format."""


class SECClient:
    """Fetch JSON over HTTP while respecting SEC access requirements."""

    RETRYABLE_STATUS_CODES = frozenset({429, 500, 502, 503, 504})

    def __init__(
        self,
        user_agent: str,
        timeout: float = 10.0,
        max_retries: int = 2,
        requests_per_second: float = 5.0,
        opener: Callable[..., Any] = urlopen,
        clock: Callable[[], float] = time.monotonic,
        sleeper: Callable[[float], None] = time.sleep,
    ) -> None:
        if not user_agent.strip():
            raise SECConfigurationError(
                "SEC_USER_AGENT must identify the application and provide "
                "contact information."
            )
        if timeout <= 0:
            raise SECConfigurationError("SEC timeout must be greater than zero.")
        if max_retries < 0:
            raise SECConfigurationError("SEC max_retries must not be negative.")
        if not 0 < requests_per_second <= 5:
            raise SECConfigurationError(
                "SEC requests_per_second must be greater than zero and at most 5."
            )

        self._user_agent = user_agent
        self._timeout = timeout
        self._max_retries = max_retries
        self._minimum_interval = 1.0 / requests_per_second
        self._opener = opener
        self._clock = clock
        self._sleeper = sleeper
        self._last_request_at: Optional[float] = None
        self._rate_limit_lock = threading.Lock()

    @classmethod
    def from_environment(cls) -> "SECClient":
        """Create a client from environment variables."""
        user_agent = os.environ.get("SEC_USER_AGENT", "")
        timeout = _read_float_environment("SEC_TIMEOUT_SECONDS", 10.0)
        max_retries = _read_int_environment("SEC_MAX_RETRIES", 2)
        requests_per_second = _read_float_environment(
            "SEC_REQUESTS_PER_SECOND", 5.0
        )
        return cls(
            user_agent=user_agent,
            timeout=timeout,
            max_retries=max_retries,
            requests_per_second=requests_per_second,
        )

    def get_json(self, url: str) -> Any:
        """GET one SEC URL and decode its JSON response."""
        for attempt in range(self._max_retries + 1):
            self._wait_for_rate_limit()
            request = Request(
                url,
                headers={
                    "User-Agent": self._user_agent,
                    "Accept": "application/json",
                },
                method="GET",
            )

            try:
                with self._opener(request, timeout=self._timeout) as response:
                    body = response.read()
                try:
                    return json.loads(body.decode("utf-8"))
                except (UnicodeDecodeError, json.JSONDecodeError) as error:
                    raise SECDataError(
                        f"SEC returned invalid JSON for {url}"
                    ) from error
            except HTTPError as error:
                if (
                    error.code not in self.RETRYABLE_STATUS_CODES
                    or attempt == self._max_retries
                ):
                    raise SECRequestError(
                        f"SEC request failed with HTTP {error.code}: {url}"
                    ) from error
            except URLError as error:
                if attempt == self._max_retries:
                    raise SECRequestError(
                        f"SEC request failed after "
                        f"{self._max_retries + 1} attempts: {url}"
                    ) from error
            except TimeoutError as error:
                if attempt == self._max_retries:
                    raise SECRequestError(
                        f"SEC request timed out after "
                        f"{self._max_retries + 1} attempts: {url}"
                    ) from error

            self._sleeper(0.5 * (2**attempt))

        raise SECRequestError(f"SEC request failed: {url}")

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


def _read_float_environment(name: str, default: float) -> float:
    value = os.environ.get(name)
    if value is None:
        return default
    try:
        return float(value)
    except ValueError as error:
        raise SECConfigurationError(f"{name} must be a number.") from error


def _read_int_environment(name: str, default: int) -> int:
    value = os.environ.get(name)
    if value is None:
        return default
    try:
        return int(value)
    except ValueError as error:
        raise SECConfigurationError(f"{name} must be an integer.") from error
