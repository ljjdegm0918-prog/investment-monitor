# -*- coding: utf-8 -*-
"""NSE corporate announcements key-free JSON client.

The public announcements JSON lives at
``GET https://www.nseindia.com/api/corporate-announcements?index=equities&from_date=...&to_date=...``.
Each item has ``seq_id`` (stable id), ``symbol``, ``sm_name``, ``sm_isin``,
``desc`` (category), ``an_dt`` (IST time), ``attchmntText`` (summary) and
``attchmntFile`` (official PDF). One calendar day can carry ~1600 rows,
so the connector filters by requested symbols after download. No paid
NSE data product is used.

The same origin often requires a homepage cookie before the JSON endpoint
answers; cloud IPs may still receive HTTP 403 from the site WAF. That is
an honest failure, not a fake empty list.
"""

from __future__ import annotations

from http.cookiejar import CookieJar
import json
import logging
import os
import threading
import time
from datetime import date
from typing import Any, Callable, List, Mapping, Optional
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import HTTPCookieProcessor, Request, build_opener

LOGGER = logging.getLogger(__name__)

DEFAULT_BASE_URL = "https://www.nseindia.com/api/corporate-announcements"
DEFAULT_HOMEPAGE = "https://www.nseindia.com/"
DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/126.0.0.0 Safari/537.36"
)


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


def _cookie_opener() -> Callable[..., Any]:
    director = build_opener(HTTPCookieProcessor(CookieJar()))

    def opener(request, timeout=None):
        return director.open(request, timeout=timeout)

    return opener


class NseAnnouncementsClient:
    """Small stdlib client for NSE corporate announcements."""

    def __init__(
        self,
        base_url: str = DEFAULT_BASE_URL,
        timeout: float = 20.0,
        max_retries: int = 2,
        requests_per_second: float = 1.0,
        user_agent: str = DEFAULT_USER_AGENT,
        opener: Optional[Callable[..., Any]] = None,
        homepage: str = DEFAULT_HOMEPAGE,
        warm_session: Optional[bool] = None,
        clock: Callable[[], float] = time.monotonic,
        sleeper: Callable[[float], None] = time.sleep,
    ) -> None:
        if not base_url.strip():
            raise ValueError("NSE announcements base URL must not be empty.")
        if timeout <= 0:
            raise ValueError("NSE announcements timeout must be greater than zero.")
        self._base_url = base_url.rstrip("/")
        self._homepage = homepage if homepage.endswith("/") else homepage + "/"
        self._timeout = timeout
        self._max_retries = max_retries
        self._minimum_interval = 1.0 / requests_per_second
        self._user_agent = user_agent
        if opener is None:
            self._opener = _cookie_opener()
            self._warm_session = True if warm_session is None else warm_session
        else:
            self._opener = opener
            self._warm_session = bool(warm_session)
        self._clock = clock
        self._sleeper = sleeper
        self._lock = threading.Lock()
        self._last_request_at = 0.0
        self._session_ready = False

    @classmethod
    def from_environment(cls) -> "NseAnnouncementsClient":
        return cls(
            base_url=os.environ.get("NSE_ANNOUNCEMENTS_BASE_URL", DEFAULT_BASE_URL),
            timeout=_environment_float("NSE_ANNOUNCEMENTS_TIMEOUT_SECONDS", 20.0),
            max_retries=int(os.environ.get("NSE_ANNOUNCEMENTS_MAX_RETRIES", "2")),
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

    def _ensure_session(self) -> None:
        if not self._warm_session or self._session_ready:
            return
        self._wait()
        request = Request(
            self._homepage,
            headers={
                "User-Agent": self._user_agent,
                "Accept": "text/html,application/xhtml+xml;q=0.9,*/*;q=0.8",
            },
        )
        try:
            with self._opener(request, timeout=self._timeout) as response:
                response.read()
        except (HTTPError, URLError, TimeoutError) as error:
            LOGGER.warning("NSE homepage session warm failed: %s", error)
        self._session_ready = True

    def fetch_day(self, day: date) -> List[Mapping[str, Any]]:
        parameters = {
            "index": "equities",
            "from_date": day.strftime("%d-%m-%Y"),
            "to_date": day.strftime("%d-%m-%Y"),
        }
        url = f"{self._base_url}?{urlencode(parameters)}"
        for attempt in range(self._max_retries + 1):
            self._ensure_session()
            self._wait()
            request = Request(
                url,
                headers={
                    "Accept": "application/json, text/plain, */*",
                    "User-Agent": self._user_agent,
                    "Referer": self._homepage,
                },
            )
            try:
                with self._opener(request, timeout=self._timeout) as response:
                    payload = json.loads(response.read().decode("utf-8"))
                if not isinstance(payload, list):
                    raise NseAnnouncementsDataError(
                        "NSE announcements response must be a list."
                    )
                return payload
            except NseAnnouncementsDataError:
                raise
            except HTTPError as error:
                if error.code == 403:
                    self._session_ready = False
                if attempt == self._max_retries:
                    raise NseAnnouncementsRequestError(
                        f"NSE announcements request failed after {attempt + 1} attempts."
                    ) from error
                self._sleeper(min(8.0, 0.5 * (2 ** attempt)))
            except (URLError, TimeoutError) as error:
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
