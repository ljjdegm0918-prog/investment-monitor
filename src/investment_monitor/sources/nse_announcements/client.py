# -*- coding: utf-8 -*-
"""NSE corporate announcements key-free JSON client.

Recon (live verified 2026-08-15):
``GET https://www.nseindia.com/api/corporate-announcements?index=equities&from_date=14-08-2026&to_date=14-08-2026``
returns JSON without any cookie/WAF (plain urllib works). Each item has
``seq_id`` (stable id), ``symbol``, ``sm_name``, ``sm_isin``, ``desc``
(category), ``an_dt`` (IST time), ``attchmntText`` (summary) and
``attchmntFile`` (official PDF). One calendar day can carry ~1600 rows,
so the connector filters by requested symbols after download. No paid
NSE data product is used.
"""

from __future__ import annotations

import json
import logging
import os
import threading
import time
from datetime import date
from typing import Any, Callable, List, Mapping, Optional
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

LOGGER = logging.getLogger(__name__)

DEFAULT_BASE_URL = "https://www.nseindia.com/api/corporate-announcements"


class NseAnnouncementsError(Exception):
    """Base error for NSE announcements collection."""


class NseAnnouncementsRequestError(NseAnnouncementsError):
    """Raised when the NSE request cannot be completed."""


class NseAnnouncementsDataError(NseAnnouncementsError):
    """Raised when NSE returns unexpected JSON."""


def _environment_float(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, str(default)))
    except ValueError as error:
        raise ValueError(f"{name} must be numeric") from error


class NseAnnouncementsClient:
    """Small stdlib client for NSE corporate announcements."""

    def __init__(
        self,
        base_url: str = DEFAULT_BASE_URL,
        timeout: float = 10.0,
        max_retries: int = 1,
        requests_per_second: float = 1.0,
        user_agent: str = "Mozilla/5.0 (compatible; InvestmentMonitor/0.1)",
        opener: Callable[..., Any] = urlopen,
        clock: Callable[[], float] = time.monotonic,
        sleeper: Callable[[float], None] = time.sleep,
    ) -> None:
        if not base_url.strip():
            raise ValueError("NSE announcements base URL must not be empty.")
        if timeout <= 0:
            raise ValueError("NSE announcements timeout must be greater than zero.")
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout
        self._max_retries = max_retries
        self._minimum_interval = 1.0 / requests_per_second
        self._user_agent = user_agent
        self._opener = opener
        self._clock = clock
        self._sleeper = sleeper
        self._lock = threading.Lock()
        self._last_request_at = 0.0

    @classmethod
    def from_environment(cls) -> "NseAnnouncementsClient":
        return cls(
            base_url=os.environ.get("NSE_ANNOUNCEMENTS_BASE_URL", DEFAULT_BASE_URL),
            timeout=_environment_float("NSE_ANNOUNCEMENTS_TIMEOUT_SECONDS", 10.0),
            max_retries=int(os.environ.get("NSE_ANNOUNCEMENTS_MAX_RETRIES", "1")),
            requests_per_second=_environment_float(
                "NSE_ANNOUNCEMENTS_REQUESTS_PER_SECOND", 1.0
            ),
        )

    def _wait(self) -> None:
        with self._lock:
            elapsed = self._clock() - self._last_request_at
            wait = self._minimum_interval - elapsed
            if wait > 0:
                self._sleeper(wait)
            self._last_request_at = self._clock()

    def fetch_day(self, day: date) -> List[Mapping[str, Any]]:
        parameters = {
            "index": "equities",
            "from_date": day.strftime("%d-%m-%Y"),
            "to_date": day.strftime("%d-%m-%Y"),
        }
        url = f"{self._base_url}?{urlencode(parameters)}"
        for attempt in range(self._max_retries + 1):
            self._wait()
            request = Request(url, headers={
                "Accept": "application/json",
                "User-Agent": self._user_agent,
            })
            try:
                with self._opener(request, timeout=self._timeout) as response:
                    payload = json.loads(response.read().decode("utf-8"))
                if not isinstance(payload, list):
                    raise NseAnnouncementsDataError(
                        "NSE announcements response must be a list."
                    )
                return payload
            except (HTTPError, URLError, TimeoutError) as error:
                if attempt == self._max_retries:
                    raise NseAnnouncementsRequestError(
                        f"NSE announcements request failed after {attempt + 1} attempts."
                    ) from error
                self._sleeper(min(8.0, 0.5 * (2 ** attempt)))
            except (json.JSONDecodeError, UnicodeDecodeError) as error:
                raise NseAnnouncementsDataError(
                    "NSE announcements returned invalid JSON."
                ) from error
        raise NseAnnouncementsRequestError("NSE announcements request failed.")
