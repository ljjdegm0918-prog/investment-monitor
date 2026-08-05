"""Companies House Public Data API client.

Base: https://api.company-information.service.gov.uk
Auth: HTTP Basic with username=API key and an empty password.
Rate limit: ~600 requests per 5 minutes; 429 responses are retried using the
Retry-After header. API keys and Authorization headers never appear in
errors/logs (see redact_secrets).
"""

from __future__ import annotations

import base64
import json
import logging
import os
import re
import threading
import time
from typing import Any, Callable, List, Mapping, Optional
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen

from ...connectors.base import ConnectorUnavailableError

LOGGER = logging.getLogger(__name__)

DEFAULT_BASE_URL = "https://api.company-information.service.gov.uk"
RETRYABLE_STATUS_CODES = frozenset({429, 500, 502, 503, 504})
AUTH_PATTERN = re.compile(r"(?i)(authorization:\s*basic\s*)[^\s]+")


class CompaniesHouseError(Exception):
    """Base error for Companies House collection."""


class CompaniesHouseRequestError(CompaniesHouseError):
    """Raised when a Companies House request cannot be completed."""

    def __init__(
        self,
        message: str,
        status_code: Optional[int] = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code


class CompaniesHouseDataError(CompaniesHouseError):
    """Raised when Companies House returns unexpected data."""


class CompaniesHouseClient:
    """Small stdlib JSON client for the Companies House Public Data API."""

    def __init__(
        self,
        api_key: str,
        base_url: str = DEFAULT_BASE_URL,
        timeout: float = 15.0,
        max_retries: int = 2,
        requests_per_second: float = 2.0,
        opener: Callable[..., Any] = urlopen,
        clock: Callable[[], float] = time.monotonic,
        sleeper: Callable[[float], None] = time.sleep,
    ) -> None:
        if not api_key.strip():
            raise ConnectorUnavailableError(
                "COMPANIES_HOUSE_API_KEY is not configured; "
                "Companies House is not connected."
            )
        if not base_url.strip():
            raise ValueError("Companies House base URL must not be empty.")
        if timeout <= 0:
            raise ValueError(
                "Companies House timeout must be greater than zero."
            )
        if max_retries < 0:
            raise ValueError(
                "Companies House max_retries must not be negative."
            )
        if requests_per_second <= 0:
            raise ValueError(
                "Companies House requests_per_second must be greater than zero."
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
        self._authorization = "Basic " + base64.b64encode(
            f"{api_key}:".encode("utf-8")
        ).decode("ascii")

    @classmethod
    def from_environment(cls) -> "CompaniesHouseClient":
        """Build a client from environment configuration."""
        api_key = os.environ.get("COMPANIES_HOUSE_API_KEY", "").strip()
        if not api_key:
            raise ConnectorUnavailableError(
                "COMPANIES_HOUSE_API_KEY is not configured; "
                "Companies House is not connected."
            )
        return cls(
            api_key=api_key,
            base_url=os.environ.get(
                "COMPANIES_HOUSE_BASE_URL",
                DEFAULT_BASE_URL,
            ),
            timeout=_read_float_environment(
                "COMPANIES_HOUSE_TIMEOUT_SECONDS",
                15.0,
            ),
            max_retries=_read_int_environment(
                "COMPANIES_HOUSE_MAX_RETRIES",
                2,
            ),
            requests_per_second=_read_float_environment(
                "COMPANIES_HOUSE_REQUESTS_PER_SECOND",
                2.0,
            ),
        )

    def get_company(self, company_number: str) -> Mapping[str, Any]:
        """Fetch a company profile by its company number."""
        payload = self.get_json(
            "/company/" + _safe_company_number(company_number)
        )
        if not isinstance(payload, dict):
            raise CompaniesHouseDataError(
                "Companies House company response must be a JSON object."
            )
        return payload

    def get_filing_history(self, company_number: str) -> List[Mapping[str, Any]]:
        """Fetch one page of filing history for a company number."""
        payload = self.get_json(
            "/company/"
            + _safe_company_number(company_number)
            + "/filing-history?items_per_page=100"
        )
        items = payload.get("items") if isinstance(payload, dict) else None
        if not isinstance(items, list):
            raise CompaniesHouseDataError(
                "Companies House filing history must contain an items list."
            )
        return items

    def search_companies(self, query: str) -> List[Mapping[str, Any]]:
        """Search companies by name/number."""
        payload = self.get_json("/search/companies?q=" + quote(query))
        items = payload.get("items") if isinstance(payload, dict) else None
        if not isinstance(items, list):
            raise CompaniesHouseDataError(
                "Companies House search must contain an items list."
            )
        return items

    def get_json(self, path: str) -> Any:
        """GET one Companies House endpoint and decode its JSON response."""
        url = f"{self._base_url}{path}"
        for attempt in range(self._max_retries + 1):
            self._wait_for_rate_limit()
            request = Request(
                url,
                headers={
                    "Authorization": self._authorization,
                    "Accept": "application/json",
                },
                method="GET",
            )
            try:
                with self._opener(request, timeout=self._timeout) as response:
                    raw_body = response.read()
                try:
                    return json.loads(raw_body.decode("utf-8"))
                except (UnicodeDecodeError, json.JSONDecodeError) as error:
                    raise CompaniesHouseDataError(
                        f"Companies House returned invalid JSON for {path}"
                    ) from error
            except HTTPError as error:
                if error.code == 429:
                    retry_after = _retry_after_seconds(error)
                    if attempt < self._max_retries:
                        self._sleeper(retry_after)
                        continue
                if (
                    error.code not in RETRYABLE_STATUS_CODES
                    or attempt == self._max_retries
                ):
                    raise CompaniesHouseRequestError(
                        f"Companies House request failed with HTTP "
                        f"{error.code}: {path}",
                        status_code=error.code,
                    ) from error
            except URLError as error:
                if attempt == self._max_retries:
                    raise CompaniesHouseRequestError(
                        f"Companies House request failed after "
                        f"{self._max_retries + 1} attempts: {path}"
                    ) from error
            except TimeoutError as error:
                if attempt == self._max_retries:
                    raise CompaniesHouseRequestError(
                        f"Companies House request timed out after "
                        f"{self._max_retries + 1} attempts: {path}"
                    ) from error
            self._sleeper(0.5 * (2**attempt))
        raise CompaniesHouseRequestError(
            f"Companies House request failed: {path}"
        )

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


def _safe_company_number(value: str) -> str:
    """Validate a company number path segment (alphanumeric, short)."""
    normalized = str(value).strip().upper()
    if not normalized or len(normalized) > 10 or not normalized.isalnum():
        raise CompaniesHouseDataError(
            f"Invalid Companies House company number: {normalized!r}"
        )
    return normalized


def _retry_after_seconds(error: HTTPError) -> float:
    value = error.headers.get("Retry-After")
    if value is None:
        return 1.0
    try:
        return min(float(value), 30.0)
    except ValueError:
        return 1.0


def redact_secrets(text: str) -> str:
    """Redact Authorization header values from error/log text."""
    return AUTH_PATTERN.sub(r"\1REDACTED", text)


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
