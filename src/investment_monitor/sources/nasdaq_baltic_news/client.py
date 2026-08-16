# -*- coding: utf-8 -*-
"""Nasdaq Baltic official news client (key-free JSON API).

Recon (live verified 2026-08-15): ``GET https://api.news.eu.nasdaq.com/
news/query.action`` is the same JSON API that powers the official
https://nasdaqbaltic.com/statistics/en/news page. It is key-free, returns
``results.item`` entries with ``disclosureId``, ``headline``, ``company``,
``cnsCategory``, ``messageUrl``, ``published``, ``market`` and PDF
``attachment`` entries. The page's JavaScript uses ``timeZone:
Europe/Tallinn`` for all three Baltic exchanges, so this client does the
same. Exchange notices are filtered out by the connector (they carry
``company: "Nasdaq Tallinn/Riga/Vilnius"`` and are not issuer-bound);
only issuer announcements are kept. No paid Nasdaq data product is used.
"""

from __future__ import annotations

import json
import logging
import os
import threading
import time
from datetime import date, datetime, timezone
from typing import Any, Callable, List, Mapping, Optional, Sequence
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

LOGGER = logging.getLogger(__name__)

DEFAULT_BASE_URL = "https://api.news.eu.nasdaq.com/news/query.action"
MAX_PAGE_ITEMS = 200
BALTIC_TIME = "Europe/Tallinn"

# API 的发行市场名（releaseMarket 参数）。
RELEASE_MARKETS = {
    "ee": ("Main Market, Tallinn", "First North Estonia"),
    "lv": ("Main Market, Riga", "First North Latvia"),
    "lt": ("Main Market, Vilnius", "First North Lithuania"),
}


class BalticNewsError(Exception):
    """Base error for Nasdaq Baltic news collection."""


class BalticNewsRequestError(BalticNewsError):
    """Raised when the Nasdaq Baltic request cannot be completed."""


class BalticNewsDataError(BalticNewsError):
    """Raised when the Nasdaq Baltic API returns an unexpected shape."""


def _environment_float(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, str(default)))
    except ValueError as error:
        raise ValueError(f"{name} must be numeric") from error


def _environment_int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, str(default)))
    except ValueError as error:
        raise ValueError(f"{name} must be numeric") from error


class BalticNewsClient:
    """Small stdlib client for the official Nasdaq Baltic news API."""

    def __init__(
        self,
        base_url: str = DEFAULT_BASE_URL,
        timeout: float = 8.0,
        max_retries: int = 1,
        requests_per_second: float = 2.0,
        user_agent: str = "InvestmentMonitor/0.1 (internal workspace)",
        opener: Callable[..., Any] = urlopen,
        clock: Callable[[], float] = time.monotonic,
        sleeper: Callable[[float], None] = time.sleep,
    ) -> None:
        if not base_url.strip():
            raise ValueError("Baltic news base URL must not be empty.")
        if timeout <= 0:
            raise ValueError("Baltic news timeout must be greater than zero.")
        if max_retries < 0:
            raise ValueError("Baltic news max_retries must not be negative.")
        if requests_per_second <= 0:
            raise ValueError("Baltic news requests_per_second must be greater than zero.")
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
    def from_environment(cls) -> "BalticNewsClient":
        return cls(
            base_url=os.environ.get("BALTIC_NEWS_BASE_URL", DEFAULT_BASE_URL),
            timeout=_environment_float("BALTIC_NEWS_TIMEOUT_SECONDS", 8.0),
            max_retries=_environment_int("BALTIC_NEWS_MAX_RETRIES", 1),
            requests_per_second=_environment_float(
                "BALTIC_NEWS_REQUESTS_PER_SECOND", 2.0
            ),
        )

    def _wait(self) -> None:
        with self._lock:
            elapsed = self._clock() - self._last_request_at
            wait = self._minimum_interval - elapsed
            if wait > 0:
                self._sleeper(wait)
            self._last_request_at = self._clock()

    def fetch_market_day(
        self,
        day: date,
        market: str,
    ) -> List[Mapping[str, Any]]:
        """Fetch issuer announcements for one Baltic market and one local day."""
        if market not in RELEASE_MARKETS:
            raise ValueError(f"Unsupported Baltic market: {market}")
        items: List[Mapping[str, Any]] = []
        seen: set[int] = set()
        for release_market in RELEASE_MARKETS[market]:
            items.extend(self._fetch_release_day(day, release_market, seen))
        return items

    def _fetch_release_day(
        self,
        day: date,
        release_market: str,
        seen: set[int],
    ) -> List[Mapping[str, Any]]:
        day_start = datetime(
            day.year, day.month, day.day, 0, 0, 0, tzinfo=timezone.utc
        )
        # 官方页面按 Europe/Tallinn 本地日界定；这里近似用 UTC 日的 24h 窗口，
        # 再由 connector 按 Tallinn 时区过滤（最大偏差约 3 小时，可接受）。
        day_end = day_start.replace(hour=23, minute=59, second=59)
        parameters = {
            "language": "en",
            "displayLanguage": "en",
            "timeZone": BALTIC_TIME,
            "limit": MAX_PAGE_ITEMS,
            "fromDate": int(day_start.timestamp() * 1000),
            "toDate": int(day_end.timestamp() * 1000),
            "releaseMarket": release_market,
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
                return self._parse_items(payload, seen)
            except (HTTPError, URLError, TimeoutError) as error:
                if attempt == self._max_retries:
                    raise BalticNewsRequestError(
                        f"Nasdaq Baltic news request failed after {attempt + 1} attempts."
                    ) from error
                self._sleeper(min(8.0, 0.5 * (2 ** attempt)))
            except (json.JSONDecodeError, UnicodeDecodeError, TypeError) as error:
                raise BalticNewsDataError(
                    "Nasdaq Baltic news API returned invalid JSON."
                ) from error
        raise BalticNewsRequestError("Nasdaq Baltic news request failed.")

    @staticmethod
    def _parse_items(
        payload: Any,
        seen: set[int],
    ) -> List[Mapping[str, Any]]:
        if not isinstance(payload, dict):
            raise BalticNewsDataError("Nasdaq Baltic news response must be an object.")
        results = payload.get("results")
        if not isinstance(results, dict):
            raise BalticNewsDataError("Nasdaq Baltic news response missing results.")
        raw_items = results.get("item")
        if not isinstance(raw_items, list):
            raise BalticNewsDataError("Nasdaq Baltic news response missing item list.")
        items: List[Mapping[str, Any]] = []
        for raw in raw_items:
            if not isinstance(raw, dict):
                continue
            disclosure_id = raw.get("disclosureId")
            if disclosure_id is None or disclosure_id in seen:
                continue
            seen.add(int(disclosure_id))
            items.append(raw)
        return items
