"""Clients for Nasdaq Nordic's official public share and company-news APIs."""

from __future__ import annotations

import json
import os
import threading
import time
from math import ceil
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

    def fetch_share_directory(
        self,
        *,
        market: str = "STO",
        page_size: int = 1000,
        max_pages: int = 100,
    ) -> List[Mapping[str, Any]]:
        """Return the official Stockholm share directory across both boards.

        The public Nasdaq Nordic screener exposes Main Market and First North
        separately.  It is tempting to request the default screen and filter
        a single page locally; that can silently mix Nordic venues or truncate
        a category.  This method instead sends Nasdaq's market/category and
        pagination parameters on every request, validates the response
        pagination contract, and requires every returned row to identify as a
        share before returning anything.
        """
        if not market.strip() or page_size <= 0 or max_pages <= 0:
            raise ValueError("market, page_size and max_pages must be valid")
        combined: List[Mapping[str, Any]] = []
        for category in ("MAIN_MARKET", "FIRST_NORTH"):
            combined.extend(
                self._fetch_share_category(
                    category=category,
                    market=market,
                    page_size=page_size,
                    max_pages=max_pages,
                )
            )
        return combined

    def _fetch_share_category(
        self,
        *,
        category: str,
        market: str,
        page_size: int,
        max_pages: int,
    ) -> List[Mapping[str, Any]]:
        records: List[Mapping[str, Any]] = []
        declared_total: int | None = None
        declared_total_pages: int | None = None
        seen_page_signatures: set[tuple[str, ...]] = set()
        seen_row_ids: set[str] = set()
        for page in range(1, max_pages + 1):
            params = {
                "market": market,
                "category": category,
                # The official component serializes its nested pagination
                # object as the flat ``page``/``size`` query parameters.
                # ``assetClass`` is a response field, not an accepted filter
                # on this endpoint (sending it currently yields HTTP 400).
                "size": str(page_size),
                "page": str(page),
                "tableonly": "false",
            }
            url = SHARES_URL + "?" + urlencode(params)
            payload = self._get_json(url)
            _validate_directory_status(payload)
            try:
                listing = payload["data"]["instrumentListing"]
                rows = listing["rows"]
                pagination = payload["data"]["pagination"]
            except (KeyError, TypeError) as error:
                raise NasdaqSeDataError(
                    "Nasdaq share directory rows or pagination are missing"
                ) from error
            if not isinstance(rows, list) or not isinstance(pagination, Mapping):
                raise NasdaqSeDataError("Nasdaq share directory shape changed")
            try:
                total = int(pagination["total"])
                size = int(pagination["size"])
                returned_page = int(pagination["page"])
                total_pages = int(pagination["totalPages"])
            except (KeyError, TypeError, ValueError) as error:
                raise NasdaqSeDataError(
                    "Nasdaq share directory pagination fields are invalid"
                ) from error
            if total < 0 or size <= 0 or returned_page != page or total_pages < 0:
                raise NasdaqSeDataError("Nasdaq share directory pagination is invalid")
            expected_pages = ceil(total / size) if total else 0
            if total_pages != expected_pages:
                raise NasdaqSeDataError(
                    "Nasdaq share directory totalPages does not match total/size"
                )
            if declared_total is None:
                declared_total, declared_total_pages = total, total_pages
            elif (total, total_pages) != (declared_total, declared_total_pages):
                raise NasdaqSeDataError(
                    "Nasdaq share directory pagination drifted between pages"
                )
            expected_rows = max(0, min(size, total - ((page - 1) * size)))
            if len(rows) != expected_rows:
                raise NasdaqSeDataError(
                    "Nasdaq share directory page row count does not match pagination"
                )
            signature = tuple(
                str(row.get("isin") or row.get("symbol") or "")
                for row in rows
                if isinstance(row, Mapping)
            )
            if len(signature) != len(rows) or len(set(signature)) != len(signature):
                raise NasdaqSeDataError("Nasdaq share directory page identity is invalid")
            if set(signature) & seen_row_ids:
                raise NasdaqSeDataError(
                    "Nasdaq share directory overlapped identities across pages"
                )
            if signature and signature in seen_page_signatures:
                raise NasdaqSeDataError("Nasdaq share directory repeated a page")
            seen_page_signatures.add(signature)
            seen_row_ids.update(signature)
            for row in rows:
                if not isinstance(row, Mapping):
                    raise NasdaqSeDataError("Nasdaq share directory row is not an object")
                asset_class = str(row.get("assetClass") or "").upper()
                if asset_class != "SHARES":
                    raise NasdaqSeDataError(
                        "Nasdaq share directory returned a non-SHARES row; "
                        "expected response assetClass=SHARES"
                    )
                records.append(
                    {
                        **row,
                        "listing_category": category,
                        "listing_market": market,
                        "retrieval_url": url,
                    }
                )
            if page == total_pages:
                break
            if page > total_pages:
                raise NasdaqSeDataError("Nasdaq share directory exceeded totalPages")
        else:
            raise NasdaqSeDataError(
                f"Nasdaq share directory exceeded max_pages={max_pages} for {category}"
            )
        if declared_total is None or len(records) != declared_total:
            raise NasdaqSeDataError(
                f"Nasdaq returned {len(records)} directory rows but declared {declared_total}"
            )
        return records

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


def _validate_directory_status(payload: Mapping[str, Any]) -> None:
    """Reject a Nasdaq screener payload whose API status is not successful."""
    status = payload.get("status")
    if isinstance(status, int):
        code = status
    elif isinstance(status, Mapping):
        value = status.get("rCode", status.get("code"))
        try:
            code = int(value)
        except (TypeError, ValueError) as error:
            raise NasdaqSeDataError("Nasdaq share directory status is invalid") from error
    else:
        raise NasdaqSeDataError("Nasdaq share directory status is missing")
    if code != 200:
        raise NasdaqSeDataError(f"Nasdaq share directory status was {code}")


def _end_of_day_ms(value: date) -> int:
    moment = datetime.combine(value, datetime_time.max, tzinfo=timezone.utc)
    return int(moment.timestamp() * 1000)


def _record_date(record: Mapping[str, Any]) -> date:
    value = str(record.get("published") or record.get("releaseTime") or "")
    try:
        return datetime.strptime(value, "%Y-%m-%d %H:%M:%S").date()
    except ValueError as error:
        raise NasdaqSeDataError("Nasdaq company-news published time is invalid") from error
