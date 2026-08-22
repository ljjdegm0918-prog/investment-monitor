"""HKEXnews (披露易) announcement search client.

Recon (verified live 2026-08-06): the active-stock JSON at
``https://www1.hkexnews.hk/ncms/script/eds/activestock_sehk_e.json`` is a
plain JSON array of ``{"i": <row>, "c": "00001", "n": "CKH HOLDINGS",
"s": 3749}`` entries, where ``s`` is the internal stock id used by the
title-search servlet (e.g. ``00700`` -> ``15157``).

The official public Title Search UI calls
``/search/titleSearchServlet.do``.  Its JSON envelope has a stringified
``result`` array with NEWS_ID / TITLE / DATE_TIME / FILE_LINK / STOCK_CODE /
STOCK_NAME / FILE_TYPE, plus ``loadedRecord`` / ``recordCnt`` /
``hasNextRow`` paging evidence.  The endpoint is a public frontend contract,
not a separately documented HKEX API, so every response is validated before
an empty result is accepted.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import threading
import time
from dataclasses import dataclass
from datetime import date, datetime, timezone, timedelta
from typing import Any, Callable, List, Mapping, Optional, Tuple
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

LOGGER = logging.getLogger(__name__)

DEFAULT_BASE_URL = "https://www1.hkexnews.hk"
TITLE_SEARCH_PATH = "/search/titleSearchServlet.do"
RETRYABLE_STATUS_CODES = frozenset({429, 500, 502, 503, 504})
HKT = timezone(timedelta(hours=8))
DEFAULT_SEARCH_ROW_RANGE = 100
DEFAULT_SEARCH_MAX_PAGES = 100


class HkexNewsError(Exception):
    """Base error for HKEXnews collection."""


class HkexNewsRequestError(HkexNewsError):
    """Raised when an HKEXnews request cannot be completed."""


class HkexNewsDataError(HkexNewsError):
    """Raised when HKEXnews returns an unexpected payload."""


@dataclass(frozen=True)
class _SearchPage:
    """One cumulative Title Search response.

    HKEXnews does not expose a conventional page/offset cursor.  Its own
    ``LOAD MORE`` control re-issues the same query with a larger ``rowRange``
    (100, 200, 300, ...), and returns all rows loaded so far.  Keeping the
    envelope metadata lets the client detect a silently truncated response
    instead of mistaking it for an empty or complete result.
    """

    records: List[Mapping[str, Any]]
    loaded_record: int
    record_count: int
    has_next_row: bool
    row_range: int


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
        search_page_size: int = DEFAULT_SEARCH_ROW_RANGE,
        search_max_pages: int = DEFAULT_SEARCH_MAX_PAGES,
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
        if search_page_size <= 0:
            raise ValueError("HKEXnews search_page_size must be greater than zero.")
        if search_max_pages <= 0:
            raise ValueError("HKEXnews search_max_pages must be greater than zero.")
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
        self._search_page_size = search_page_size
        self._search_max_pages = search_max_pages

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

    def fetch_stock_list(
        self,
        status: str = "active",
        lang: str = "e",
    ) -> List[Mapping[str, Any]]:
        """Fetch one HKEXnews stock list parsed into normalized rows.

        ``status`` is ``active`` or ``inactive``; ``lang`` is ``e`` or ``c``.
        Rows carry stock_code / stock_id / stock_name keys.
        """
        if status not in ("active", "inactive"):
            raise ValueError(
                "HKEXnews stock list status must be active or inactive."
            )
        if lang not in ("e", "c"):
            raise ValueError("HKEXnews stock list lang must be 'e' or 'c'.")
        url = (
            f"{self._base_url}/ncms/script/eds/"
            f"{status}stock_sehk_{lang}.json"
        )
        data = self._get_json(url)
        return _parse_stock_list(data)

    def search_disclosures(
        self,
        stock_id: str,
        start_date: date,
        end_date: date,
        lang: str = "E",
    ) -> List[Mapping[str, Any]]:
        """Search every announcement in the requested date window.

        The official Title Search frontend initially requests 100 rows then
        repeats the identical query with ``rowRange`` increased by 100 until
        ``hasNextRow`` is false.  Do the same here and fail closed if the
        public envelope cannot prove that all reported rows were received.
        """
        if end_date < start_date:
            raise ValueError("HKEXnews end_date must not be before start_date.")
        response_lang = _canonical_search_language(lang)
        loaded: List[Mapping[str, Any]] = []
        previous_ids: Tuple[str, ...] = ()

        for page_number in range(1, self._search_max_pages + 1):
            row_range = self._search_page_size * page_number
            page = self._search_page(
                stock_id=stock_id,
                start_date=start_date,
                end_date=end_date,
                lang=response_lang,
                row_range=row_range,
            )
            current_ids = tuple(str(record["news_id"]) for record in page.records)
            if len(set(current_ids)) != len(current_ids):
                raise HkexNewsDataError(
                    "HKEXnews title search returned duplicate NEWS_ID values."
                )
            if previous_ids and current_ids[: len(previous_ids)] != previous_ids:
                raise HkexNewsDataError(
                    "HKEXnews title search changed or dropped earlier rows while loading more."
                )
            if page.loaded_record != len(page.records):
                raise HkexNewsDataError(
                    "HKEXnews title search loadedRecord did not match returned rows."
                )
            if page.record_count < page.loaded_record:
                raise HkexNewsDataError(
                    "HKEXnews title search recordCnt was smaller than loadedRecord."
                )
            if page.has_next_row != (page.loaded_record < page.record_count):
                raise HkexNewsDataError(
                    "HKEXnews title search paging metadata was contradictory."
                )
            if page.has_next_row and page.loaded_record <= len(previous_ids):
                raise HkexNewsDataError(
                    "HKEXnews title search did not make progress while loading more."
                )

            loaded = page.records
            previous_ids = current_ids
            if not page.has_next_row:
                return loaded

        raise HkexNewsDataError(
            "HKEXnews title search reached the configured pagination limit before completion."
        )

    def _search_page(
        self,
        *,
        stock_id: str,
        start_date: date,
        end_date: date,
        lang: str,
        row_range: int,
    ) -> _SearchPage:
        """Fetch one cumulative Title Search envelope using the official UI contract."""
        params = {
            # These are the fields sent by ncms/js/titlesearch_research.js.
            "sortDir": "0",
            "sortByOptions": "0",
            "category": "",
            "market": "SEHK",
            "stockId": str(stock_id),
            "documentType": "",
            "fromDate": start_date.strftime("%Y%m%d"),
            "toDate": end_date.strftime("%Y%m%d"),
            "title": "",
            "searchType": "1",
            "t1code": "-2",
            "t2Gcode": "-2",
            "t2code": "-2",
            "rowRange": str(row_range),
            "lang": lang,
        }
        url = f"{self._base_url}{TITLE_SEARCH_PATH}?{urlencode(params)}"
        data = self._get_json(url)
        return _parse_search_response(
            data,
            base_url=self._base_url,
            expected_lang=lang,
        )

    def _load_stock_list(self) -> List[Mapping[str, Any]]:
        now = self._clock()
        if self._stock_cache is not None:
            fetched_at, cached = self._stock_cache
            if now - fetched_at < self._stock_list_ttl_seconds:
                return cached
        # Title Search retains historical announcements for delisted issuers.
        # Looking only at the active list silently turns those valid requests
        # into an apparent no-result, so preserve active entries preferentially
        # and append inactive-only securities.
        active = self.fetch_stock_list("active", "e")
        inactive = self.fetch_stock_list("inactive", "e")
        by_code = {str(row["stock_code"]): row for row in active}
        for row in inactive:
            by_code.setdefault(str(row["stock_code"]), row)
        rows = list(by_code.values())
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
    expected_lang: str,
) -> _SearchPage:
    if not isinstance(data, dict):
        raise HkexNewsDataError(
            "HKEXnews title search returned an unexpected payload."
        )
    required_fields = (
        "result",
        "hasNextRow",
        "rowRange",
        "lang",
        "loadedRecord",
        "recordCnt",
    )
    missing = tuple(field for field in required_fields if field not in data)
    if missing:
        raise HkexNewsDataError(
            "HKEXnews title search envelope was missing required fields: "
            + ", ".join(missing)
            + "."
        )
    raw_result = data["result"]
    if isinstance(raw_result, str):
        try:
            rows = json.loads(raw_result)
        except (TypeError, ValueError) as error:
            raise HkexNewsDataError(
                "HKEXnews title search result was not valid JSON."
            ) from error
    else:
        rows = raw_result
    if not isinstance(rows, list):
        raise HkexNewsDataError(
            "HKEXnews title search result was not a list."
        )
    has_next_row = data["hasNextRow"]
    if not isinstance(has_next_row, bool):
        raise HkexNewsDataError(
            "HKEXnews title search hasNextRow was not a boolean."
        )
    response_lang = str(data["lang"] or "").strip().upper()
    if response_lang != expected_lang:
        raise HkexNewsDataError(
            "HKEXnews title search response language did not match the request."
        )
    row_range = _parse_nonnegative_int(data["rowRange"], "rowRange")
    loaded_record = _parse_nonnegative_int(
        data["loadedRecord"], "loadedRecord"
    )
    record_count = _parse_nonnegative_int(data["recordCnt"], "recordCnt")
    if row_range == 0:
        raise HkexNewsDataError(
            "HKEXnews title search rowRange must be greater than zero."
        )
    records: List[Mapping[str, Any]] = []
    for index, row in enumerate(rows):
        if not isinstance(row, dict):
            raise HkexNewsDataError(
                f"HKEXnews title search row {index} was not an object."
            )
        news_id = str(row.get("NEWS_ID") or "").strip()
        title = str(row.get("TITLE") or "").strip()
        file_link = str(row.get("FILE_LINK") or "").strip()
        published_at = _parse_hkt_datetime(
            str(row.get("DATE_TIME") or "").strip()
        )
        stock_code = str(row.get("STOCK_CODE") or "").strip()
        stock_name = str(row.get("STOCK_NAME") or "").strip()
        file_type = str(row.get("FILE_TYPE") or "").strip()
        if (
            not news_id
            or not title
            or not file_link
            or published_at is None
            or not stock_code
            or not stock_name
            or not file_type
        ):
            raise HkexNewsDataError(
                f"HKEXnews title search row {index} was missing required announcement fields."
            )
        url = (
            file_link
            if file_link.startswith("http")
            else f"{base_url}{file_link}"
        )
        records.append(
            {
                "news_id": news_id,
                "title": title,
                "published_at": published_at,
                "url": url,
                "stock_code": stock_code,
                "stock_name": stock_name,
                "file_type": file_type,
                "file_link": file_link,
            }
        )
    return _SearchPage(
        records=records,
        loaded_record=loaded_record,
        record_count=record_count,
        has_next_row=has_next_row,
        row_range=row_range,
    )


def _parse_nonnegative_int(value: Any, field: str) -> int:
    """Parse a non-negative count without accepting booleans or decimals."""
    if isinstance(value, bool):
        raise HkexNewsDataError(
            f"HKEXnews title search {field} was not a non-negative integer."
        )
    try:
        parsed = int(str(value))
    except (TypeError, ValueError) as error:
        raise HkexNewsDataError(
            f"HKEXnews title search {field} was not a non-negative integer."
        ) from error
    if parsed < 0 or str(value).strip() not in {str(parsed), f"+{parsed}"}:
        raise HkexNewsDataError(
            f"HKEXnews title search {field} was not a non-negative integer."
        )
    return parsed


def _canonical_search_language(lang: str) -> str:
    """Map public caller aliases to the E/C codes sent by the HKEX UI."""
    normalized = str(lang).strip().lower()
    if normalized in {"e", "en", "eng", "english"}:
        return "E"
    if normalized in {"c", "zh", "zh-hk", "chi", "chinese"}:
        return "C"
    raise ValueError("HKEXnews search lang must be English or Chinese.")


def _parse_stock_list(data: Any) -> List[Mapping[str, Any]]:
    """Parse an HKEXnews ``i/c/n/s`` stock list into normalized rows."""
    if not isinstance(data, list):
        raise HkexNewsDataError("HKEXnews stock list was not a JSON array.")
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
            "HKEXnews stock list contained no usable entries."
        )
    return rows


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
