"""HKEXnews (披露易) announcement search client.

Recon (verified live 2026-08-06): the active-stock JSON at
``https://www1.hkexnews.hk/ncms/script/eds/activestock_sehk_e.json`` is a
plain JSON array of ``{"i": <row>, "c": "00001", "n": "CKH HOLDINGS",
"s": 3749}`` entries, where ``s`` is the internal stock id used by the
title-search servlet (e.g. ``00700`` -> ``15157``).

``/search/titleSearchServlet.do`` returns a JSON envelope whose ``result``
field is a *stringified* JSON array of rows carrying NEWS_ID / TITLE /
DATE_TIME / FILE_LINK / STOCK_CODE / STOCK_NAME / FILE_TYPE. This is an
unofficial, undocumented page API and may change without notice. From the
current network the servlet consistently returns an empty envelope (likely
geo/session gating), so behaviour is locked with fixtures instead of live
data.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import threading
import time
from datetime import date, datetime, timezone, timedelta
from typing import Any, Callable, List, Mapping, Optional, Tuple
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

LOGGER = logging.getLogger(__name__)

DEFAULT_BASE_URL = "https://www1.hkexnews.hk"
TITLE_SEARCH_PATH = "/search/titleSearchServlet.do"
ACTIVE_STOCK_PATH = "/ncms/script/eds/activestock_sehk_e.json"
RETRYABLE_STATUS_CODES = frozenset({429, 500, 502, 503, 504})
HKT = timezone(timedelta(hours=8))


class HkexNewsError(Exception):
    """Base error for HKEXnews collection."""


class HkexNewsRequestError(HkexNewsError):
    """Raised when an HKEXnews request cannot be completed."""


class HkexNewsDataError(HkexNewsError):
    """Raised when HKEXnews returns an unexpected payload."""


def normalize_hk_ticker(ticker: str) -> str:
    """Normalize a Hong Kong stock code to its canonical five-digit form.

    Mirrors ``web_repository.normalize_hk_ticker``; keeps both copies in
    sync so the connector can run without importing the repository layer.
    """
    cleaned = str(ticker).strip().upper()
    core = (
        cleaned.removesuffix(".HK")
        .removesuffix(" HK")
        .removesuffix("-HK")
    )
    if core.isdigit():
        return core.zfill(5)
    return cleaned


def stable_fallback_id(url: str) -> str:
    """Stable hash fallback when the servlet omits NEWS_ID."""
    return hashlib.sha1(url.encode("utf-8")).hexdigest()


class HkexNewsClient:
    """Small stdlib JSON client for HKEXnews active stocks and announcements."""

    def __init__(
        self,
        base_url: str = DEFAULT_BASE_URL,
        timeout: float = 20.0,
        max_retries: int = 1,
        requests_per_second: float = 2.0,
        user_agent: str = "InvestmentMonitor/0.1 (internal workspace)",
        opener: Callable[..., Any] = urlopen,
        clock: Callable[[], float] = time.monotonic,
        sleeper: Callable[[float], None] = time.sleep,
        stock_list_ttl_seconds: float = 3600.0,
    ) -> None:
        if not base_url.strip():
            raise ValueError("HKEXnews base URL must not be empty.")
        if timeout <= 0:
            raise ValueError("HKEXnews timeout must be greater than zero.")
        if max_retries < 0:
            raise ValueError("HKEXnews max_retries must not be negative.")
        if requests_per_second <= 0:
            raise ValueError(
                "HKEXnews requests_per_second must be greater than zero."
            )
        if stock_list_ttl_seconds < 0:
            raise ValueError(
                "HKEXnews stock_list_ttl_seconds must not be negative."
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
        self._stock_list_ttl_seconds = stock_list_ttl_seconds
        self._stock_cache: Optional[Tuple[float, List[Mapping[str, Any]]]] = None

    @classmethod
    def from_environment(cls) -> "HkexNewsClient":
        return cls(
            base_url=os.environ.get("HKEXNEWS_BASE_URL", DEFAULT_BASE_URL),
            timeout=_read_float_environment(
                "HKEXNEWS_TIMEOUT_SECONDS",
                20.0,
            ),
            max_retries=_read_int_environment(
                "HKEXNEWS_MAX_RETRIES",
                1,
            ),
            requests_per_second=_read_float_environment(
                "HKEXNEWS_REQUESTS_PER_SECOND",
                2.0,
            ),
        )

    def stock_id_for(self, ticker: str) -> Optional[str]:
        """Return the internal HKEXnews stock id, or None when unknown."""
        stock = self.stock_for(ticker)
        if stock is None:
            return None
        return str(stock["stock_id"])

    def stock_for(self, ticker: str) -> Optional[Mapping[str, Any]]:
        """Return active-stock metadata for a normalized HK ticker."""
        code = normalize_hk_ticker(ticker)
        for row in self._load_stock_list():
            if str(row["stock_code"]) == code:
                return row
        return None

    def search_disclosures(
        self,
        stock_id: str,
        start_date: date,
        end_date: date,
        lang: str = "E",
    ) -> List[Mapping[str, Any]]:
        """Search announcements for one stock; returns normalized records."""
        params = {
            "market": "SEHK",
            "stockId": str(stock_id),
            "searchType": "1",
            "fromDate": start_date.strftime("%Y%m%d"),
            "toDate": end_date.strftime("%Y%m%d"),
            "rowRange": "50",
            "lang": lang,
        }
        url = f"{self._base_url}{TITLE_SEARCH_PATH}?{urlencode(params)}"
        data = self._get_json(url)
        return _parse_search_response(data, base_url=self._base_url)

    def _load_stock_list(self) -> List[Mapping[str, Any]]:
        now = self._clock()
        if self._stock_cache is not None:
            fetched_at, cached = self._stock_cache
            if now - fetched_at < self._stock_list_ttl_seconds:
                return cached
        url = f"{self._base_url}{ACTIVE_STOCK_PATH}"
        data = self._get_json(url)
        if not isinstance(data, list):
            raise HkexNewsDataError(
                "HKEXnews active stock list was not a JSON array."
            )
        rows: List[Mapping[str, Any]] = []
        for entry in data:
            if not isinstance(entry, dict):
                continue
            code = str(entry.get("c") or "").strip()
            stock_id = str(entry.get("s") or "").strip()
            name = str(entry.get("n") or "").strip()
            if code and stock_id:
                rows.append(
                    {
                        "stock_code": code,
                        "stock_id": stock_id,
                        "stock_name": name,
                    }
                )
        if not rows:
            raise HkexNewsDataError(
                "HKEXnews active stock list contained no usable entries."
            )
        self._stock_cache = (now, rows)
        return rows

    def _get_json(self, url: str) -> Any:
        for attempt in range(self._max_retries + 1):
            self._wait_for_rate_limit()
            request = Request(
                url,
                headers={
                    "User-Agent": self._user_agent,
                    "Accept": "application/json,text/javascript,*/*;q=0.8",
                    "Accept-Language": "en-US,en;q=0.9,zh-HK;q=0.8",
                },
                method="GET",
            )
            try:
                with self._opener(request, timeout=self._timeout) as response:
                    raw = response.read()
                return json.loads(raw.decode("utf-8", errors="replace"))
            except HTTPError as error:
                if (
                    error.code not in RETRYABLE_STATUS_CODES
                    or attempt == self._max_retries
                ):
                    raise HkexNewsRequestError(
                        "HKEXnews request failed with HTTP "
                        f"{error.code}: {url}"
                    ) from error
            except URLError as error:
                if attempt == self._max_retries:
                    raise HkexNewsRequestError(
                        "HKEXnews request failed after "
                        f"{self._max_retries + 1} attempts: {url}"
                    ) from error
            except TimeoutError as error:
                if attempt == self._max_retries:
                    raise HkexNewsRequestError(
                        "HKEXnews request timed out after "
                        f"{self._max_retries + 1} attempts: {url}"
                    ) from error
            except (json.JSONDecodeError, UnicodeDecodeError) as error:
                raise HkexNewsDataError(
                    "HKEXnews response was not valid JSON."
                ) from error
            self._sleeper(0.5 * (2**attempt))
        raise HkexNewsRequestError(f"HKEXnews request failed: {url}")

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


def _parse_search_response(
    data: Any,
    *,
    base_url: str,
) -> List[Mapping[str, Any]]:
    if not isinstance(data, dict):
        raise HkexNewsDataError(
            "HKEXnews title search returned an unexpected payload."
        )
    raw_result = data.get("result")
    if isinstance(raw_result, str):
        try:
            rows = json.loads(raw_result)
        except (TypeError, ValueError) as error:
            raise HkexNewsDataError(
                "HKEXnews title search result was not valid JSON."
            ) from error
    else:
        rows = raw_result
    if rows is None:
        return []
    if not isinstance(rows, list):
        raise HkexNewsDataError(
            "HKEXnews title search result was not a list."
        )
    records: List[Mapping[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        title = str(row.get("TITLE") or "").strip()
        file_link = str(row.get("FILE_LINK") or "").strip()
        published_at = _parse_hkt_datetime(
            str(row.get("DATE_TIME") or "").strip()
        )
        if not title or not file_link or published_at is None:
            continue
        url = (
            file_link
            if file_link.startswith("http")
            else f"{base_url}{file_link}"
        )
        records.append(
            {
                "news_id": str(row.get("NEWS_ID") or "").strip(),
                "title": title,
                "published_at": published_at,
                "url": url,
                "stock_code": str(row.get("STOCK_CODE") or "").strip(),
                "stock_name": str(row.get("STOCK_NAME") or "").strip(),
                "file_type": str(row.get("FILE_TYPE") or "").strip(),
                "file_link": file_link,
            }
        )
    return records


_DATE_FORMATS = (
    ("%Y-%m-%d %H:%M:%S", False),
    ("%Y-%m-%d %H:%M", False),
    ("%d/%m/%Y %H:%M", False),
    ("%Y-%m-%d", True),
    ("%Y%m%d", True),
)


def _parse_hkt_datetime(value: str) -> Optional[datetime]:
    if not value:
        return None
    for fmt, date_only in _DATE_FORMATS:
        try:
            parsed = datetime.strptime(value, fmt)
        except ValueError:
            continue
        if date_only:
            parsed = parsed.replace(hour=0, minute=0)
        return parsed.replace(tzinfo=HKT).astimezone(timezone.utc)
    return None


def _read_float_environment(name: str, default: float) -> float:
    value = os.environ.get(name)
    if value is None:
        return default
    try:
        return float(value)
    except ValueError:
        return default


def _read_int_environment(name: str, default: int) -> int:
    value = os.environ.get(name)
    if value is None:
        return default
    try:
        return int(value)
    except ValueError:
        return default
