# -*- coding: utf-8 -*-
"""Client for BSE India's public corporate-announcements service.

The BSE corporate-announcement page at
``https://www.bseindia.com/corporates/ann.html`` uses the two first-party
endpoints implemented here.  Live recon on 2026-08-17 established that:

* ``ListofScripData/w?segment=Equity&status=Active`` returns the official
  BSE security directory with ``SCRIP_CD``, ``scrip_id`` and ``ISIN_NUMBER``;
* ``AnnSubCategoryGetData/w`` accepts an inclusive ``YYYYMMDD`` date window,
  a BSE scrip code, and a one-based ``pageno``;
* the response's ``Table1[0].ROWCNT`` is the total number of records, while
  each announcement has its native UUID ``NEWSID`` and ``ATTACHMENTNAME``.

This is the public website backend, not BSE's paid market-data product.  The
endpoint is undocumented and may change; malformed or truncated responses are
raised as data errors rather than silently represented as an empty result.
"""

from __future__ import annotations

import json
import os
import threading
import time
from datetime import date
from typing import Any, Callable, List, Mapping, Optional, Sequence, Tuple
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

DEFAULT_API_BASE_URL = "https://api.bseindia.com/BseIndiaAPI/api"
DEFAULT_ANNOUNCEMENTS_URL = (
    f"{DEFAULT_API_BASE_URL}/AnnSubCategoryGetData/w"
)
DEFAULT_SECURITIES_URL = f"{DEFAULT_API_BASE_URL}/ListofScripData/w"
ATTACHMENT_BASE_URL = "https://www.bseindia.com/xml-data/corpfiling/AttachLive"
REFERER = "https://www.bseindia.com/corporates/ann.html"
RETRYABLE_HTTP_STATUS_CODES = frozenset({429, 500, 502, 503, 504})


class BseIndiaAnnouncementsError(Exception):
    """Base error for BSE India announcement collection."""


class BseIndiaAnnouncementsRequestError(BseIndiaAnnouncementsError):
    """Raised when BSE India's public endpoint cannot be reached."""


class BseIndiaAnnouncementsDataError(BseIndiaAnnouncementsError):
    """Raised for unexpected or internally inconsistent BSE payloads."""


def _environment_float(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, str(default)))
    except ValueError as error:
        raise ValueError(f"{name} must be numeric") from error


def _environment_int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, str(default)))
    except ValueError as error:
        raise ValueError(f"{name} must be an integer") from error


class BseIndiaAnnouncementsClient:
    """Rate-limited, dependency-free BSE public announcements client."""

    def __init__(
        self,
        announcements_url: str = DEFAULT_ANNOUNCEMENTS_URL,
        securities_url: str = DEFAULT_SECURITIES_URL,
        timeout: float = 20.0,
        max_retries: int = 1,
        requests_per_second: float = 0.5,
        max_pages_per_scrip: int = 100,
        user_agent: str = "Mozilla/5.0 (compatible; InvestmentMonitor/0.1)",
        opener: Callable[..., Any] = urlopen,
        clock: Callable[[], float] = time.monotonic,
        sleeper: Callable[[float], None] = time.sleep,
    ) -> None:
        if not announcements_url.strip():
            raise ValueError("BSE announcements URL must not be empty.")
        if not securities_url.strip():
            raise ValueError("BSE securities URL must not be empty.")
        if timeout <= 0:
            raise ValueError("BSE announcements timeout must be greater than zero.")
        if max_retries < 0:
            raise ValueError("BSE announcements max_retries must not be negative.")
        if requests_per_second <= 0:
            raise ValueError("BSE announcements requests_per_second must be greater than zero.")
        if max_pages_per_scrip <= 0:
            raise ValueError("BSE announcements max_pages_per_scrip must be positive.")
        self._announcements_url = announcements_url
        self._securities_url = securities_url
        self._timeout = timeout
        self._max_retries = max_retries
        self._minimum_interval = 1.0 / requests_per_second
        self._max_pages_per_scrip = max_pages_per_scrip
        self._user_agent = user_agent
        self._opener = opener
        self._clock = clock
        self._sleeper = sleeper
        self._rate_lock = threading.Lock()
        self._last_request_at: Optional[float] = None
        self._security_cache: Optional[Tuple[Mapping[str, Any], ...]] = None

    @classmethod
    def from_environment(cls) -> "BseIndiaAnnouncementsClient":
        return cls(
            announcements_url=os.environ.get(
                "BSE_INDIA_ANNOUNCEMENTS_URL", DEFAULT_ANNOUNCEMENTS_URL
            ),
            securities_url=os.environ.get(
                "BSE_INDIA_SECURITIES_URL", DEFAULT_SECURITIES_URL
            ),
            timeout=_environment_float("BSE_INDIA_TIMEOUT_SECONDS", 20.0),
            max_retries=_environment_int("BSE_INDIA_MAX_RETRIES", 1),
            requests_per_second=_environment_float(
                "BSE_INDIA_REQUESTS_PER_SECOND", 0.5
            ),
            max_pages_per_scrip=_environment_int(
                "BSE_INDIA_MAX_PAGES_PER_SCRIP", 100
            ),
        )

    def fetch_securities(self) -> List[Mapping[str, Any]]:
        """Return BSE's active-equity directory, cached for this client."""
        if self._security_cache is None:
            payload = self._get_json(
                f"{self._securities_url}?{urlencode({'segment': 'Equity', 'status': 'Active'})}"
            )
            if not isinstance(payload, list):
                raise BseIndiaAnnouncementsDataError(
                    "BSE securities response must be a list."
                )
            rows: List[Mapping[str, Any]] = []
            for row in payload:
                if not isinstance(row, Mapping):
                    raise BseIndiaAnnouncementsDataError(
                        "BSE securities response contains a non-object row."
                    )
                if not str(row.get("SCRIP_CD") or "").strip():
                    raise BseIndiaAnnouncementsDataError(
                        "BSE security row is missing SCRIP_CD."
                    )
                rows.append(dict(row))
            self._security_cache = tuple(rows)
        return [dict(row) for row in self._security_cache]

    def fetch_announcements(
        self,
        scrip_code: str,
        start_date: date,
        end_date: date,
    ) -> List[Mapping[str, Any]]:
        """Fetch all announced records for one BSE security and date window."""
        if end_date < start_date:
            raise ValueError("BSE announcement end_date must not precede start_date.")
        code = str(scrip_code).strip()
        if not code:
            raise ValueError("BSE scrip code must not be empty.")

        records: List[Mapping[str, Any]] = []
        seen_news_ids: set[str] = set()
        total: Optional[int] = None
        for page_number in range(1, self._max_pages_per_scrip + 1):
            page_rows, page_total = self._fetch_page(
                code, start_date, end_date, page_number
            )
            if total is None:
                total = page_total
            elif total != page_total:
                raise BseIndiaAnnouncementsDataError(
                    "BSE announcement total changed during pagination."
                )
            page_ids = [str(row["NEWSID"]).strip() for row in page_rows]
            if len(set(page_ids)) != len(page_ids) or seen_news_ids.intersection(page_ids):
                raise BseIndiaAnnouncementsDataError(
                    "BSE announcement pagination returned duplicate NEWSID values."
                )
            seen_news_ids.update(page_ids)
            records.extend(page_rows)
            if len(records) >= total:
                return records[:total]
            if not page_rows:
                raise BseIndiaAnnouncementsDataError(
                    "BSE announcement pagination ended before ROWCNT records were received."
                )
        raise BseIndiaAnnouncementsDataError(
            "BSE announcement pagination exceeded max_pages_per_scrip."
        )

    def attachment_url(self, attachment_name: Any) -> str:
        """Return an official public attachment URL, or an empty string."""
        name = str(attachment_name or "").strip().lstrip("/")
        if not name:
            return ""
        if "/" in name or "\\" in name:
            raise BseIndiaAnnouncementsDataError(
                "BSE attachment name must not contain a path separator."
            )
        return f"{ATTACHMENT_BASE_URL}/{name}"

    def _fetch_page(
        self,
        scrip_code: str,
        start_date: date,
        end_date: date,
        page_number: int,
    ) -> Tuple[List[Mapping[str, Any]], int]:
        parameters = {
            "pageno": page_number,
            "strCat": "-1",
            "strPrevDate": start_date.strftime("%Y%m%d"),
            "strScrip": scrip_code,
            "strSearch": "P",
            "strToDate": end_date.strftime("%Y%m%d"),
            "strType": "C",
            "subcategory": "",
        }
        payload = self._get_json(
            f"{self._announcements_url}?{urlencode(parameters)}"
        )
        # BSE sometimes returns this literal for a legitimate empty scrip window.
        if payload == "No Record Found!":
            return [], 0
        if not isinstance(payload, Mapping):
            raise BseIndiaAnnouncementsDataError(
                "BSE announcements response must be an object."
            )
        table = payload.get("Table")
        table1 = payload.get("Table1")
        if not isinstance(table, list) or not isinstance(table1, list) or not table1:
            raise BseIndiaAnnouncementsDataError(
                "BSE announcements response is missing Table or Table1."
            )
        count_row = table1[0]
        if not isinstance(count_row, Mapping):
            raise BseIndiaAnnouncementsDataError(
                "BSE announcements Table1 row must be an object."
            )
        row_count = count_row.get("ROWCNT")
        if row_count is None:
            raise BseIndiaAnnouncementsDataError(
                "BSE announcements ROWCNT must be an integer."
            )
        try:
            total = int(row_count)
        except (TypeError, ValueError) as error:
            raise BseIndiaAnnouncementsDataError(
                "BSE announcements ROWCNT must be an integer."
            ) from error
        if total < 0:
            raise BseIndiaAnnouncementsDataError(
                "BSE announcements ROWCNT must not be negative."
            )
        rows: List[Mapping[str, Any]] = []
        for row in table:
            if not isinstance(row, Mapping):
                raise BseIndiaAnnouncementsDataError(
                    "BSE announcements Table contains a non-object row."
                )
            if not str(row.get("NEWSID") or "").strip():
                raise BseIndiaAnnouncementsDataError(
                    "BSE announcement row is missing NEWSID."
                )
            rows.append(dict(row))
        if len(rows) > total:
            raise BseIndiaAnnouncementsDataError(
                "BSE announcements page contains more records than ROWCNT."
            )
        return rows, total

    def _get_json(self, url: str) -> Any:
        for attempt in range(self._max_retries + 1):
            self._wait_for_rate_limit()
            request = Request(
                url,
                headers={
                    "Accept": "application/json, text/plain, */*",
                    "Referer": REFERER,
                    "User-Agent": self._user_agent,
                },
                method="GET",
            )
            try:
                with self._opener(request, timeout=self._timeout) as response:
                    raw = response.read()
                return json.loads(raw.decode("utf-8"))
            except HTTPError as error:
                if (
                    error.code not in RETRYABLE_HTTP_STATUS_CODES
                    or attempt == self._max_retries
                ):
                    raise BseIndiaAnnouncementsRequestError(
                        f"BSE India request failed with HTTP {error.code}: {url}"
                    ) from error
            except (URLError, TimeoutError, OSError) as error:
                if attempt == self._max_retries:
                    raise BseIndiaAnnouncementsRequestError(
                        f"BSE India request failed after {attempt + 1} attempts: {url}"
                    ) from error
            except (json.JSONDecodeError, UnicodeDecodeError) as error:
                raise BseIndiaAnnouncementsDataError(
                    "BSE India returned invalid JSON."
                ) from error
            self._sleeper(0.5 * (2**attempt))
        raise BseIndiaAnnouncementsRequestError(f"BSE India request failed: {url}")

    def _wait_for_rate_limit(self) -> None:
        with self._rate_lock:
            now = self._clock()
            if self._last_request_at is not None:
                remaining = self._minimum_interval - (now - self._last_request_at)
                if remaining > 0:
                    self._sleeper(remaining)
                    now = self._clock()
            self._last_request_at = now
