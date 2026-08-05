"""OpenDART HTTP client with status checks and secret redaction."""

from __future__ import annotations

import json
import logging
import os
import re
import threading
import time
from typing import Any, Callable, List, Mapping, Optional
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from ...connectors.base import ConnectorUnavailableError

LOGGER = logging.getLogger(__name__)

DEFAULT_BASE_URL = "https://opendart.fss.or.kr/api"
RETRYABLE_STATUS_CODES = frozenset({429, 500, 502, 503, 504})
CRTFC_KEY_PATTERN = re.compile(r"crtfc_key=[^&#\s]*")


class DartError(Exception):
    """Base error for OpenDART collection."""


class DartRequestError(DartError):
    """Raised when an OpenDART request cannot be completed."""

    def __init__(self, message: str, status_code: Optional[str] = None) -> None:
        super().__init__(message)
        self.status_code = status_code


class DartDataError(DartError):
    """Raised when OpenDART returns data in an unexpected format."""


class DartClient:
    """Small stdlib JSON/binary client for the OpenDART API."""

    def __init__(
        self,
        api_key: str,
        base_url: str = DEFAULT_BASE_URL,
        timeout: float = 10.0,
        max_retries: int = 2,
        requests_per_second: float = 5.0,
        opener: Callable[..., Any] = urlopen,
        clock: Callable[[], float] = time.monotonic,
        sleeper: Callable[[float], None] = time.sleep,
    ) -> None:
        if not api_key.strip():
            raise ConnectorUnavailableError(
                "DART_API_KEY is not configured; OpenDART is not connected."
            )
        if not base_url.strip():
            raise ValueError("OpenDART base URL must not be empty.")
        if timeout <= 0:
            raise ValueError("OpenDART timeout must be greater than zero.")
        if max_retries < 0:
            raise ValueError("OpenDART max_retries must not be negative.")
        if requests_per_second <= 0:
            raise ValueError(
                "OpenDART requests_per_second must be greater than zero."
            )
        self._api_key = api_key
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout
        self._max_retries = max_retries
        self._minimum_interval = 1.0 / requests_per_second
        self._opener = opener
        self._clock = clock
        self._sleeper = sleeper
        self._last_request_at: Optional[float] = None
        self._rate_limit_lock = threading.Lock()

    @classmethod
    def from_environment(cls) -> "DartClient":
        """Build a client from environment configuration."""
        api_key = os.environ.get("DART_API_KEY", "").strip()
        if not api_key:
            raise ConnectorUnavailableError(
                "DART_API_KEY is not configured; OpenDART is not connected."
            )
        return cls(
            api_key=api_key,
            base_url=os.environ.get(
                "DART_BASE_URL",
                DEFAULT_BASE_URL,
            ),
            timeout=_read_float_environment("DART_TIMEOUT_SECONDS", 10.0),
            max_retries=_read_int_environment("DART_MAX_RETRIES", 2),
            requests_per_second=_read_float_environment(
                "DART_REQUESTS_PER_SECOND",
                5.0,
            ),
        )

    def get_json(
        self,
        path: str,
        parameters: Mapping[str, str],
    ) -> Mapping[str, Any]:
        """GET one OpenDART JSON endpoint and return its decoded object."""
        payload = self._request(path, parameters, json_response=True)
        if not isinstance(payload, dict):
            raise DartDataError("OpenDART response must be a JSON object.")
        return payload

    def get_bytes(
        self,
        path: str,
        parameters: Mapping[str, str],
    ) -> bytes:
        """GET one OpenDART endpoint and return its raw bytes."""
        payload = self._request(path, parameters, json_response=False)
        if not isinstance(payload, bytes):
            raise DartDataError("OpenDART binary response is invalid.")
        return payload

    def get_list(
        self,
        *,
        corp_code: str,
        bgn_de: str,
        end_de: str,
    ) -> List[Mapping[str, Any]]:
        """Fetch disclosure list records for one corp code and date range."""
        payload = self.get_json(
            "list.json",
            {
                "corp_code": corp_code,
                "bgn_de": bgn_de,
                "end_de": end_de,
            },
        )
        status = str(payload.get("status") or "")
        if status == "000":
            records = payload.get("list") or []
            if not isinstance(records, list):
                raise DartDataError(
                    "OpenDART list response must contain a list array."
                )
            return records
        if status == "200":
            return []
        message = str(payload.get("message") or status)
        raise DartRequestError(
            f"OpenDART list status {status}: {message}",
            status_code=status,
        )

    def _request(
        self,
        path: str,
        parameters: Mapping[str, str],
        *,
        json_response: bool,
    ) -> Any:
        query = urlencode(
            {**dict(parameters), "crtfc_key": self._api_key}
        )
        url = f"{self._base_url}/{path.lstrip('/')}?{query}"
        safe_url = _redact_secrets(url)
        for attempt in range(self._max_retries + 1):
            self._wait_for_rate_limit()
            request = Request(
                url,
                headers={"Accept": "application/json"},
                method="GET",
            )
            try:
                with self._opener(request, timeout=self._timeout) as response:
                    body = response.read()
                if not json_response:
                    return body
                try:
                    return json.loads(body.decode("utf-8"))
                except (UnicodeDecodeError, json.JSONDecodeError) as error:
                    raise DartDataError(
                        f"OpenDART returned invalid JSON for {safe_url}"
                    ) from error
            except HTTPError as error:
                if (
                    error.code not in RETRYABLE_STATUS_CODES
                    or attempt == self._max_retries
                ):
                    raise DartRequestError(
                        f"OpenDART request failed with HTTP {error.code}: "
                        f"{safe_url}"
                    ) from error
            except URLError as error:
                if attempt == self._max_retries:
                    raise DartRequestError(
                        f"OpenDART request failed after "
                        f"{self._max_retries + 1} attempts: {safe_url}"
                    ) from error
            except TimeoutError as error:
                if attempt == self._max_retries:
                    raise DartRequestError(
                        f"OpenDART request timed out after "
                        f"{self._max_retries + 1} attempts: {safe_url}"
                    ) from error
            self._sleeper(0.5 * (2**attempt))
        raise DartRequestError(f"OpenDART request failed: {safe_url}")

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


def _redact_secrets(text: str) -> str:
    """Replace ``crtfc_key=`` values so errors/logs never leak API keys."""
    return CRTFC_KEY_PATTERN.sub("crtfc_key=REDACTED", text)


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
