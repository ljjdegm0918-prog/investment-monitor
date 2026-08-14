"""Clients for Nasdaq Nordic's official public share and company-news APIs."""

from __future__ import annotations

import json
import os
import threading
import time
from datetime import date, datetime, time as datetime_time, timedelta, timezone
from typing import Any, Callable, Dict, List, Mapping, Sequence
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

SHARES_URL = "https://api.nasdaq.com/api/nordic/screener/shares"
NEWS_URL = "https://api.news.eu.nasdaq.com/news/query.action"
METADATA_URL = "https://api.news.eu.nasdaq.com/news/metadata.action"
RETRYABLE_STATUS_CODES = frozenset({429, 500, 502, 503, 504})


class NasdaqSeError(Exception):
    """Base error for Nasdaq Sweden collection."""


class NasdaqSeRequestError(NasdaqSeError):
    """The official endpoint could not be read."""


class NasdaqSeDataError(NasdaqSeError):
    """The official endpoint returned an unexpected or truncated payload."""


class NasdaqSeClient:
    """Key-free client that follows the parameters used by Nasdaq's own UI."""

    def __init__(
        self,
        *,
        timeout: float = 20.0,
        max_retries: int = 1,
        requests_per_second: float = 1.0,
        user_agent: str = "InvestmentMonitor/0.1 (official Nasdaq Nordic)",
        opener: Callable[..., Any] = urlopen,
        clock: Callable[[], float] = time.monotonic,
        sleeper: Callable[[float], None] = time.sleep,
    ) -> None:
        self._timeout = timeout
        self._max_retries = max_retries
        self._minimum_interval = 1.0 / requests_per_second
        self._user_agent = user_agent
        self._opener = opener
        self._clock = clock
        self._sleeper = sleeper
        self._last_request_at: float | None = None
        self._lock = threading.Lock()

    @classmethod
    def from_environment(cls) -> "NasdaqSeClient":
        return cls(
            timeout=float(os.environ.get("NASDAQ_SE_TIMEOUT_SECONDS", "20")),
            max_retries=int(os.environ.get("NASDAQ_SE_MAX_RETRIES", "1")),
            requests_per_second=float(
                os.environ.get("NASDAQ_SE_REQUESTS_PER_SECOND", "1")
            ),
        )

    def fetch_share_directory(self) -> List[Mapping[str, Any]]:
        combined: List[Mapping[str, Any]] = []
        for category in ("MAIN_MARKET", "FIRST_NORTH"):
            payload = self._get_json(
                SHARES_URL + "?" + urlencode({"category": category, "tableonly": "false"})
            )
            try:
                rows = payload["data"]["instrumentListing"]["rows"]
            except (KeyError, TypeError) as error:
                raise NasdaqSeDataError("Nasdaq share directory rows are missing") from error
            if not isinstance(rows, list):
                raise NasdaqSeDataError("Nasdaq share directory rows are not a list")
            combined.extend({**row, "listing_category": category} for row in rows)
        return combined

    def fetch_company_names(self, global_name: str, market: str) -> List[str]:
        params = _base_params(global_name, market)
        params["resultType"] = "company"
        payload = self._get_json(METADATA_URL + "?" + urlencode(params))
        facts = payload.get("facts")
        if not isinstance(facts, list):
            raise NasdaqSeDataError("Nasdaq company metadata facts are missing")
        names = [str(fact.get("id") or "").strip() for fact in facts if isinstance(fact, dict)]
        return [name for name in names if name]

    def fetch_announcements(
        self,
        company: str,
        start_date: date,
        end_date: date,
        *,
        global_name: str,
        market: str,
        page_size: int = 100,
        max_pages: int = 100,
    ) -> List[Mapping[str, Any]]:
        records: List[Mapping[str, Any]] = []
        for page in range(max_pages):
            params = _base_params(global_name, market)
            params.update(
                {
                    "limit": str(page_size),
                    "start": str(page * page_size),
                    "company": company,
                    # Nasdaq treats fromDate as a strict lower bound.  Its own
                    # UI sends end-of-day milliseconds, so use the preceding
                    # day to make the requested first calendar day inclusive.
                    "fromDate": str(_end_of_day_ms(start_date - timedelta(days=1))),
                    "toDate": str(_end_of_day_ms(end_date)),
                }
            )
            url = NEWS_URL + "?" + urlencode(params)
            payload = self._get_json(url)
            try:
                result = payload["results"]
                items = result.get("item", [])
                total = int(payload["count"])
            except (KeyError, TypeError, ValueError) as error:
                raise NasdaqSeDataError("Nasdaq company-news result shape changed") from error
            if not isinstance(items, list):
                raise NasdaqSeDataError("Nasdaq company-news items are not a list")
            for item in items:
                if not isinstance(item, dict):
                    raise NasdaqSeDataError("Nasdaq company-news item is not an object")
                records.append({**item, "retrieval_url": url})
            if len(records) >= total:
                break
            if not items:
                raise NasdaqSeDataError(
                    f"Nasdaq returned an empty page before count={total} was reached"
                )
        else:
            raise NasdaqSeDataError(
                f"Nasdaq results exceed max_pages={max_pages} for {company}"
            )
        if len(records) != total:
            raise NasdaqSeDataError(
                f"Nasdaq returned {len(records)} records but declared count={total}"
            )
        return [
            record
            for record in records
            if start_date <= _record_date(record) <= end_date
        ]

    def _get_json(self, url: str) -> Mapping[str, Any]:
        for attempt in range(self._max_retries + 1):
            self._wait()
            request = Request(
                url,
                headers={"User-Agent": self._user_agent, "Accept": "application/json"},
            )
            try:
                with self._opener(request, timeout=self._timeout) as response:
                    payload = json.loads(response.read().decode("utf-8"))
                if not isinstance(payload, dict):
                    raise NasdaqSeDataError("Nasdaq JSON root is not an object")
                return payload
            except HTTPError as error:
                if error.code not in RETRYABLE_STATUS_CODES or attempt == self._max_retries:
                    raise NasdaqSeRequestError(f"Nasdaq request failed with HTTP {error.code}") from error
            except (URLError, TimeoutError) as error:
                if attempt == self._max_retries:
                    raise NasdaqSeRequestError("Nasdaq request failed after retries") from error
            except (UnicodeDecodeError, json.JSONDecodeError) as error:
                raise NasdaqSeDataError("Nasdaq response was not valid UTF-8 JSON") from error
            self._sleeper(0.5 * (2**attempt))
        raise NasdaqSeRequestError("Nasdaq request failed")

    def _wait(self) -> None:
        with self._lock:
            now = self._clock()
            if self._last_request_at is not None:
                remaining = self._minimum_interval - (now - self._last_request_at)
                if remaining > 0:
                    self._sleeper(remaining)
                    now = self._clock()
            self._last_request_at = now


def _base_params(global_name: str, market: str) -> Dict[str, str]:
    return {
        "countResults": "true",
        "globalGroup": "exchangeNotice",
        "displayLanguage": "en",
        "timeZone": "CET",
        "dateMask": "yyyy-MM-dd HH:mm:ss",
        "limit": "100",
        "start": "0",
        "dir": "DESC",
        "globalName": global_name,
        "freeText": "",
        "cnsCategory": "",
        "notCnsCategory": "",
        "market": market,
        "company": "",
        "fromDate": "",
        "toDate": "",
    }


def _end_of_day_ms(value: date) -> int:
    moment = datetime.combine(value, datetime_time.max, tzinfo=timezone.utc)
    return int(moment.timestamp() * 1000)


def _record_date(record: Mapping[str, Any]) -> date:
    value = str(record.get("published") or record.get("releaseTime") or "")
    try:
        return datetime.strptime(value, "%Y-%m-%d %H:%M:%S").date()
    except ValueError as error:
        raise NasdaqSeDataError("Nasdaq company-news published time is invalid") from error
