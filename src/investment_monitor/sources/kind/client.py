"""KIND (kind.krx.co.kr) disclosure search client.

KIND does not publish a stable third-party Open API. This client follows the
public search page's own form submission (``searchDisclosureByCorpSub``) and
parses the returned HTML fragment. Request URL, form fields, and parsing are
kept in this module so fixture tests lock the behavior; a site redesign
surfaces as a ``KindDataError`` instead of fake success.
"""

from __future__ import annotations

import html
import logging
import os
import re
import threading
import time
from datetime import date
from typing import Any, Callable, List, Mapping, Optional
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

LOGGER = logging.getLogger(__name__)

DEFAULT_BASE_URL = "https://kind.krx.co.kr"
SEARCH_PATH = "/disclosure/searchdisclosurebycorp.do"
VIEWER_PATH = (
    "/common/disclsviewer.do?method=searchInitInfo&acptNo={acpt_no}&docNo="
)
RETRYABLE_STATUS_CODES = frozenset({429, 500, 502, 503, 504})
DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/126.0 Safari/537.36"
)


class KindError(Exception):
    """Base error for KIND collection."""


class KindRequestError(KindError):
    """Raised when a KIND request cannot be completed."""


class KindDataError(KindError):
    """Raised when KIND returns data in an unexpected format."""


class KindClient:
    """Small stdlib form client for KIND's public disclosure search."""

    def __init__(
        self,
        base_url: str = DEFAULT_BASE_URL,
        timeout: float = 15.0,
        max_retries: int = 2,
        requests_per_second: float = 2.0,
        user_agent: str = DEFAULT_USER_AGENT,
        opener: Callable[..., Any] = urlopen,
        clock: Callable[[], float] = time.monotonic,
        sleeper: Callable[[float], None] = time.sleep,
    ) -> None:
        if not base_url.strip():
            raise ValueError("KIND base URL must not be empty.")
        if timeout <= 0:
            raise ValueError("KIND timeout must be greater than zero.")
        if max_retries < 0:
            raise ValueError("KIND max_retries must not be negative.")
        if requests_per_second <= 0:
            raise ValueError(
                "KIND requests_per_second must be greater than zero."
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
    def from_environment(cls) -> "KindClient":
        """Build a client from environment configuration."""
        return cls(
            base_url=os.environ.get("KIND_BASE_URL", DEFAULT_BASE_URL),
            timeout=_read_float_environment("KIND_TIMEOUT_SECONDS", 15.0),
            max_retries=_read_int_environment("KIND_MAX_RETRIES", 2),
            requests_per_second=_read_float_environment(
                "KIND_REQUESTS_PER_SECOND",
                2.0,
            ),
        )

    def search_disclosures(
        self,
        stock_code: str,
        start_date: date,
        end_date: date,
    ) -> List[Mapping[str, Any]]:
        """Search disclosures for one KR stock code and date range."""
        code = stock_code.strip()
        form = {
            "method": "searchDisclosureByCorpSub",
            "forward": "searchdisclosurebycorp_sub",
            "currentPageSize": "100",
            "pageIndex": "1",
            "orderIndex": "1",
            "orderMode": "1",
            "orderStat": "D",
            "searchMode": "1",
            "searchCodeType": "number",
            "searchCorpName": code,
            "repIsuSrtCd": "A" + code,
            "allRepIsuSrtCd": "A" + code,
            "reportNm": "",
            "reportCd": "",
            "fromDate": start_date.isoformat(),
            "toDate": end_date.isoformat(),
            "lastReport": "",
        }
        body = self._post_form(SEARCH_PATH, form)
        text = body.decode("utf-8", errors="replace")
        return _parse_disclosure_html(text)

    def _post_form(self, path: str, form: Mapping[str, str]) -> bytes:
        url = f"{self._base_url}{path}"
        payload = urlencode(dict(form)).encode("utf-8")
        for attempt in range(self._max_retries + 1):
            self._wait_for_rate_limit()
            request = Request(
                url,
                data=payload,
                headers={
                    "User-Agent": self._user_agent,
                    "Content-Type": (
                        "application/x-www-form-urlencoded; charset=UTF-8"
                    ),
                    "Accept": "text/html,application/xhtml+xml,*/*;q=0.8",
                    "Accept-Language": "ko-KR,ko;q=0.9,en;q=0.8",
                    "Referer": (
                        f"{self._base_url}/disclosure/"
                        "searchdisclosurebycorp.do"
                        "?method=searchDisclosureByCorpMain"
                    ),
                },
                method="POST",
            )
            try:
                with self._opener(request, timeout=self._timeout) as response:
                    return response.read()
            except HTTPError as error:
                if (
                    error.code not in RETRYABLE_STATUS_CODES
                    or attempt == self._max_retries
                ):
                    raise KindRequestError(
                        f"KIND request failed with HTTP {error.code}: {path}"
                    ) from error
            except URLError as error:
                if attempt == self._max_retries:
                    raise KindRequestError(
                        f"KIND request failed after "
                        f"{self._max_retries + 1} attempts: {path}"
                    ) from error
            except TimeoutError as error:
                if attempt == self._max_retries:
                    raise KindRequestError(
                        f"KIND request timed out after "
                        f"{self._max_retries + 1} attempts: {path}"
                    ) from error
            self._sleeper(0.5 * (2**attempt))
        raise KindRequestError(f"KIND request failed: {path}")

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

    def viewer_url(self, acpt_no: str) -> str:
        """Return a stable KIND disclosure viewer URL for an acceptance no."""
        return (
            f"{self._base_url}{VIEWER_PATH.format(acpt_no=acpt_no)}"
        )


def _parse_disclosure_html(text: str) -> List[Mapping[str, Any]]:
    """Parse the KIND by-company search HTML fragment into records."""
    if "조회된 결과값이 없습니다" in text:
        return []
    if "페이지 오류" in text or "잠시 후 다시 이용해 주세요" in text:
        raise KindDataError(
            "KIND returned a service error page instead of a disclosure list."
        )
    if "<table" not in text or "<tbody" not in text:
        raise KindDataError(
            "KIND response did not contain a disclosure table."
        )

    records: List[Mapping[str, Any]] = []
    row_pattern = re.compile(r"<tr[^>]*>(.*?)</tr>", re.S)
    for row_html in row_pattern.findall(text):
        viewer = re.search(
            r"openDisclsViewer\('(\d{14})'",
            row_html,
        )
        if viewer is None:
            continue
        acpt_no = viewer.group(1)
        title_match = re.search(
            r"openDisclsViewer\('[^']*','[^']*'\)[^>]*title=[\"']"
            r"([^\"']+)[\"']",
            row_html,
        )
        title = ""
        if title_match is not None:
            title = html.unescape(title_match.group(1)).strip()
        if not title:
            anchor_text = re.search(
                r"openDisclsViewer\([^)]*\)[^>]*>(.*?)</a>",
                row_html,
                re.S,
            )
            if anchor_text is not None:
                title = html.unescape(
                    re.sub(r"<[^>]+>", "", anchor_text.group(1))
                ).strip()
        if not title:
            continue

        company_match = re.search(
            r"companysummary_open\('[^']*'\)[^>]*title=[\"']"
            r"([^\"']+)[\"']",
            row_html,
        )
        company_name = (
            html.unescape(company_match.group(1)).strip()
            if company_match is not None
            else ""
        )
        datetime_match = re.search(
            r"(\d{4})-(\d{2})-(\d{2}) (\d{2}):(\d{2})",
            row_html,
        )
        datetime_text = (
            datetime_match.group(0) if datetime_match is not None else ""
        )
        market_match = re.search(
            r"icn_t_[a-z0-9]+\.gif'[^>]*alt=[\"']([^\"']+)[\"']",
            row_html,
        )
        market = (
            html.unescape(market_match.group(1)).strip()
            if market_match is not None
            else ""
        )
        cells = re.findall(r"<td[^>]*>(.*?)</td>", row_html, re.S)
        cell_texts = [
            html.unescape(re.sub(r"<[^>]+>", " ", cell)).strip()
            for cell in cells
        ]
        submitter = next(
            (
                value
                for value in reversed(cell_texts)
                if value and value not in {"", "공시차트", "주가차트"}
            ),
            "",
        )
        records.append(
            {
                "acpt_no": acpt_no,
                "rcept_no": acpt_no,
                "title": title,
                "company_name": company_name,
                "datetime_text": datetime_text,
                "market": market,
                "submitter": submitter,
            }
        )
    return records


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
