"""ASX company announcements JSON client.

Recon (verified live 2026-08-08): ``GET https://asx.api.markitdigital.com/
asx-research/1.0/companies/{CODE}/announcements`` returns the JSON used by
the official ASX company announcements page (``data.items`` with
``documentKey``, ``date``, ``headline``, ``announcementType``,
``fileSize``, ``isPriceSensitive``). Key-free and no login; the endpoint is
an undocumented internal API of the ASX site and may change without notice.
It always returns the latest five announcements per company (no pagination),
so companies with more than five items in the lookback window may be
partial. Items do not carry a deep document URL (``url`` is empty), so the
stable per-company announcement-list URL is used and the ``documentKey`` is
kept in metadata. Parse failures raise a data error instead of fake success.
"""

from __future__ import annotations

import json
import logging
import os
import threading
import time
from datetime import date, datetime, timezone
from typing import Any, Callable, List, Mapping, Optional
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen

LOGGER = logging.getLogger(__name__)

DEFAULT_BASE_URL = (
    "https://asx.api.markitdigital.com/asx-research/1.0/companies"
)
RETRYABLE_STATUS_CODES = frozenset({429, 500, 502, 503, 504})


class AsxAnnouncementsError(Exception):
    """Base error for ASX announcements collection."""


class AsxAnnouncementsRequestError(AsxAnnouncementsError):
    """Raised when the ASX request cannot be completed."""


class AsxAnnouncementsDataError(AsxAnnouncementsError):
    """Raised when ASX returns an unexpected payload."""


class AsxAnnouncementsClient:
    """Small stdlib JSON client for ASX company announcements."""

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
            raise ValueError("ASX announcements base URL must not be empty.")
        if timeout <= 0:
            raise ValueError(
                "ASX announcements timeout must be greater than zero."
            )
        if max_retries < 0:
            raise ValueError(
                "ASX announcements max_retries must not be negative."
            )
        if requests_per_second <= 0:
            raise ValueError(
                "ASX announcements requests_per_second must be greater "
                "than zero."
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
    def from_environment(cls) -> "AsxAnnouncementsClient":
        return cls(
            base_url=os.environ.get(
                "ASX_ANNOUNCEMENTS_URL",
                DEFAULT_BASE_URL,
            ),
            timeout=_read_float_environment(
                "ASX_ANNOUNCEMENTS_TIMEOUT_SECONDS",
                20.0,
            ),
            max_retries=_read_int_environment(
                "ASX_ANNOUNCEMENTS_MAX_RETRIES",
                1,
            ),
            requests_per_second=_read_float_environment(
                "ASX_ANNOUNCEMENTS_REQUESTS_PER_SECOND",
                1.0,
            ),
        )

    def fetch_announcements(
        self,
        code: str,
        start_date: date,
        end_date: date,
    ) -> List[Mapping[str, Any]]:
        """Fetch and parse the latest ASX announcements for a company code."""
        list_url = f"{self._base_url}/{quote(code)}/announcements"
        payload = self._get_json(list_url)
        return _parse_payload(
            payload,
            list_url=list_url,
            start_date=start_date,
            end_date=end_date,
        )

    def _get_json(self, url: str) -> Any:
        for attempt in range(self._max_retries + 1):
            self._wait_for_rate_limit()
            request = Request(
                url,
                headers={
                    "User-Agent": self._user_agent,
                    "Accept": "application/json",
                    "Accept-Language": "en-AU,en;q=0.9",
                },
                method="GET",
            )
            try:
                with self._opener(request, timeout=self._timeout) as response:
                    raw = response.read()
                try:
                    return json.loads(raw.decode("utf-8", errors="replace"))
                except json.JSONDecodeError as error:
                    raise AsxAnnouncementsDataError(
                        "ASX announcements response is not valid JSON."
                    ) from error
            except AsxAnnouncementsDataError:
                raise
            except HTTPError as error:
                if (
                    error.code not in RETRYABLE_STATUS_CODES
                    or attempt == self._max_retries
                ):
                    raise AsxAnnouncementsRequestError(
                        f"ASX announcements request failed with HTTP "
                        f"{error.code}: {url}"
                    ) from error
            except URLError as error:
                if attempt == self._max_retries:
                    raise AsxAnnouncementsRequestError(
                        f"ASX announcements request failed after "
                        f"{self._max_retries + 1} attempts: {url}"
                    ) from error
            except TimeoutError as error:
                if attempt == self._max_retries:
                    raise AsxAnnouncementsRequestError(
                        f"ASX announcements request timed out after "
                        f"{self._max_retries + 1} attempts: {url}"
                    ) from error
            self._sleeper(0.5 * (2**attempt))
        raise AsxAnnouncementsRequestError(
            f"ASX announcements request failed: {url}"
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


def _parse_payload(
    payload: Any,
    *,
    list_url: str,
    start_date: date,
    end_date: date,
) -> List[Mapping[str, Any]]:
    if not isinstance(payload, dict):
        raise AsxAnnouncementsDataError(
            "ASX announcements response was not a JSON object."
        )
    data = payload.get("data")
    items = data.get("items") if isinstance(data, dict) else None
    if not isinstance(items, list):
        raise AsxAnnouncementsDataError(
            "ASX announcements response had no items list."
        )
    records: List[Mapping[str, Any]] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        document_key = str(item.get("documentKey") or "").strip()
        headline = str(item.get("headline") or "").strip()
        published = _parse_date(str(item.get("date") or ""))
        if not document_key or not headline or published is None:
            continue
        if not start_date <= published.date() <= end_date:
            continue
        records.append(
            {
                "external_id": document_key,
                "title": headline,
                "published": published,
                "announcement_type": str(
                    item.get("announcementType") or ""
                ).strip(),
                "file_size": str(item.get("fileSize") or "").strip(),
                "is_price_sensitive": bool(item.get("isPriceSensitive")),
                "url": list_url,
            }
        )
    return records


def _parse_date(value: str) -> Optional[datetime]:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


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
