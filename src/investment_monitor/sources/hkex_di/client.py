"""HKEX Disclosure of Interests (DI) public search client.

Recon (verified live 2026-08-06, stdlib only):
- Entry: ``https://di.hkex.com.hk/filing/di/NSSrchMethod.aspx`` is a link
  page; the company search form is
  ``https://di.hkex.com.hk/filing/di/NSSrchCorp.aspx?`` (ASP.NET with
  ``__VIEWSTATE``/``__EVENTVALIDATION``; fields ``txtStockCode``,
  ``txtCorpName``, ``ddlStartDateDD/MM/YYYY``, ``ddlEndDateDD/MM/YYYY`` and
  submit ``cmdSearch=Search``).
- A POST with an in-range window lands on
  ``NSSrchCorpList.aspx?sa1=cl&scsd=DD/MM/YYYY&sced=DD/MM/YYYY&sc=<code>&``;
  a real row was observed for 00700 (Tencent Holdings Ltd. / report type).
- The site is an archive: its banner says notices run "From 1 April 2003 To
  2 October 2017" and the year dropdowns stop at 2017. Current-year windows
  fail server-side with an Error.htm redirect; notice-level detail rows sit
  behind JS/session state (Akamai Bot Manager cookies ``bm_s``/``bm_so`` are
  set). ``https://sdinotice.hkex.com.hk/`` requires login (DION issuer side).
- Conclusion: current DI notices are BLOCKED_LIVE from this network. The
  connector is disabled by default; when enabled, out-of-archive windows are
  skipped silently (log only), while real parse failures still raise
  ``HkexDiDataError`` instead of faking success. Parsing is locked by
  fixtures.
"""

from __future__ import annotations

import hashlib
import logging
import os
import re
import threading
import time
from datetime import date, datetime
from http.cookiejar import CookieJar
from typing import Any, Callable, Dict, List, Mapping, Optional, Tuple
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode
from urllib.request import (
    HTTPCookieProcessor,
    Request,
    build_opener,
)
from zoneinfo import ZoneInfo

from ...daily import date_only_market_noon
from ..hkexnews.client import normalize_hk_ticker

LOGGER = logging.getLogger(__name__)

DEFAULT_BASE_URL = "https://di.hkex.com.hk/filing/di"
ARCHIVE_START = date(2003, 4, 1)
ARCHIVE_END = date(2017, 10, 2)
RETRYABLE_STATUS_CODES = frozenset({429, 500, 502, 503, 504})
DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/126.0 Safari/537.36"
)
HKT = ZoneInfo("Asia/Hong_Kong")
class HkexDiError(Exception):
    """Base error for HKEX DI collection."""


class HkexDiRequestError(HkexDiError):
    """Raised when an HKEX DI request cannot be completed."""


class HkexDiDataError(HkexDiError):
    """Raised when HKEX DI returns an unexpected or unavailable page."""


def _default_opener() -> Callable[..., Any]:
    # Bound ``open`` so the client can call ``opener(request, timeout=...)``
    # exactly like ``urlopen`` while still keeping a session cookie jar.
    return build_opener(HTTPCookieProcessor(CookieJar())).open


class HkexDiClient:
    """Small stdlib ASP.NET form client for the HKEX DI archive search."""

    def __init__(
        self,
        base_url: str = DEFAULT_BASE_URL,
        timeout: float = 20.0,
        max_retries: int = 1,
        requests_per_second: float = 1.0,
        user_agent: str = DEFAULT_USER_AGENT,
        opener: Optional[Callable[..., Any]] = None,
        clock: Callable[[], float] = time.monotonic,
        sleeper: Callable[[float], None] = time.sleep,
    ) -> None:
        if not base_url.strip():
            raise ValueError("HKEX DI base URL must not be empty.")
        if timeout <= 0:
            raise ValueError("HKEX DI timeout must be greater than zero.")
        if max_retries < 0:
            raise ValueError("HKEX DI max_retries must not be negative.")
        if requests_per_second <= 0:
            raise ValueError(
                "HKEX DI requests_per_second must be greater than zero."
            )
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout
        self._max_retries = max_retries
        self._minimum_interval = 1.0 / requests_per_second
        self._user_agent = user_agent
        self._opener = opener or _default_opener()
        self._clock = clock
        self._sleeper = sleeper
        self._last_request_at: Optional[float] = None
        self._rate_limit_lock = threading.Lock()

    @classmethod
    def from_environment(cls) -> "HkexDiClient":
        return cls(
            base_url=os.environ.get("HKEX_DI_BASE_URL", DEFAULT_BASE_URL),
            timeout=_read_float_environment("HKEX_DI_TIMEOUT_SECONDS", 20.0),
            max_retries=_read_int_environment("HKEX_DI_MAX_RETRIES", 1),
            requests_per_second=_read_float_environment(
                "HKEX_DI_REQUESTS_PER_SECOND",
                1.0,
            ),
        )

    def search_disclosures(
        self,
        stock_code: str,
        start_date: date,
        end_date: date,
        lang: str = "EN",
    ) -> List[Mapping[str, Any]]:
        """Search archived DI notices for one HK stock and date range."""
        code = normalize_hk_ticker(stock_code)
        if end_date < ARCHIVE_START or start_date > ARCHIVE_END:
            LOGGER.info(
                "hkex_di ticker=%s window_out_of_archive skipped "
                "(public search covers 2003-04-01 to 2017-10-02)",
                code,
            )
            return []
        search_url = (
            f"{self._base_url}/NSSrchCorp.aspx?lang={quote(lang)}"
        )
        _final_url, body = self._get(search_url)
        hidden = _parse_hidden_fields(
            body.decode("utf-8", errors="replace")
        )
        if "__VIEWSTATE" not in hidden or "__EVENTVALIDATION" not in hidden:
            raise HkexDiDataError(
                "HKEX DI search page did not contain ASP.NET state fields."
            )
        form: Dict[str, str] = dict(hidden)
        form.update(
            {
                "txtStockCode": code,
                "txtCorpName": "",
                "ddlStartDateDD": f"{start_date.day:02d}",
                "ddlStartDateMM": f"{start_date.month:02d}",
                "ddlStartDateYYYY": str(start_date.year),
                "ddlEndDateDD": f"{end_date.day:02d}",
                "ddlEndDateMM": f"{end_date.month:02d}",
                "ddlEndDateYYYY": str(end_date.year),
                "cmdSearch": "Search",
            }
        )
        final_url, body = self._post(
            f"{self._base_url}/NSSrchCorp.aspx",
            form,
        )
        text = body.decode("utf-8", errors="replace")
        if "Error.htm" in final_url:
            raise HkexDiDataError(
                "HKEX DI search failed server-side "
                "(out-of-range date or blocked request)."
            )
        records = _parse_notice_rows(body, base_url=self._base_url)
        if records:
            return records
        if _parse_report_type_rows(text):
            raise HkexDiDataError(
                "HKEX DI returned only report-type summaries; notice detail "
                "requires JS/session and is unavailable to this client."
            )
        return []

    def _get(self, url: str) -> Tuple[str, bytes]:
        return self._request(url, data=None)

    def _post(self, url: str, form: Mapping[str, str]) -> Tuple[str, bytes]:
        return self._request(
            url,
            data=urlencode(form).encode("utf-8"),
        )

    def _request(
        self,
        url: str,
        *,
        data: Optional[bytes],
    ) -> Tuple[str, bytes]:
        for attempt in range(self._max_retries + 1):
            self._wait_for_rate_limit()
            headers = {
                "User-Agent": self._user_agent,
                "Accept": "text/html,application/xhtml+xml,*/*;q=0.8",
                "Accept-Language": "en-US,en;q=0.9,zh-HK;q=0.8",
            }
            if data is not None:
                headers["Content-Type"] = "application/x-www-form-urlencoded"
            request = Request(url, data=data, headers=headers, method="POST" if data is not None else "GET")
            try:
                with self._opener(request, timeout=self._timeout) as response:
                    return str(response.geturl()), response.read()
            except HTTPError as error:
                if (
                    error.code not in RETRYABLE_STATUS_CODES
                    or attempt == self._max_retries
                ):
                    raise HkexDiRequestError(
                        "HKEX DI request failed with HTTP "
                        f"{error.code}: {url}"
                    ) from error
            except URLError as error:
                if attempt == self._max_retries:
                    raise HkexDiRequestError(
                        "HKEX DI request failed after "
                        f"{self._max_retries + 1} attempts: {url}"
                    ) from error
            except TimeoutError as error:
                if attempt == self._max_retries:
                    raise HkexDiRequestError(
                        "HKEX DI request timed out after "
                        f"{self._max_retries + 1} attempts: {url}"
                    ) from error
            self._sleeper(0.5 * (2**attempt))
        raise HkexDiRequestError(f"HKEX DI request failed: {url}")

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


def _parse_hidden_fields(html: str) -> Dict[str, str]:
    fields: Dict[str, str] = {}
    for name, value in re.findall(
        r'<input[^>]*name="([^"]+)"[^>]*value="([^"]*)"',
        html,
    ):
        fields[name] = value
    for name, value in re.findall(
        r'<input[^>]*value="([^"]*)"[^>]*name="([^"]+)"',
        html,
    ):
        fields.setdefault(name, value)
    return fields


def _parse_notice_rows(
    html: bytes,
    *,
    base_url: str,
) -> List[Mapping[str, Any]]:
    text = html.decode("utf-8", errors="replace")
    records: List[Mapping[str, Any]] = []
    for row in re.findall(r"<tr[^>]*>(.*?)</tr>", text, re.S):
        cells = [
            re.sub(r"<[^>]+>", " ", cell).strip()
            for cell in re.findall(r"<td[^>]*>(.*?)</td>", row, re.S)
        ]
        if len(cells) < 3 or "serial" in cells[0].lower():
            continue
        serial = re.sub(r"[^0-9]", "", cells[0])
        if not serial:
            continue
        published_at = _parse_hk_date(cells[1])
        if published_at is None:
            continue
        person = cells[2] if len(cells) > 2 else ""
        reason = cells[3] if len(cells) > 3 else ""
        shares = cells[4] if len(cells) > 4 else ""
        pct = cells[5] if len(cells) > 5 else ""
        link = re.search(r'href="([^"]+)"', row)
        url = _absolute_url(base_url, link.group(1)) if link else ""
        if not url:
            continue
        records.append(
            {
                "serial": serial,
                "date_text": cells[1],
                "published_at": published_at,
                "person": person,
                "reason": reason,
                "shares": shares,
                "pct": pct,
                "url": url,
                "title": reason or person or f"DI notice {serial}",
            }
        )
    return records


def _parse_report_type_rows(html: str) -> List[Mapping[str, str]]:
    rows: List[Mapping[str, str]] = []
    for row in re.findall(r"<tr[^>]*>(.*?)</tr>", html, re.S):
        cells = [
            re.sub(r"<[^>]+>", " ", cell).strip()
            for cell in re.findall(r"<td[^>]*>(.*?)</td>", row, re.S)
        ]
        if cells and re.fullmatch(r"\d{5}", cells[0]):
            rows.append(
                {
                    "stock_code": cells[0],
                    "name": cells[1] if len(cells) > 1 else "",
                    "report_type": cells[2] if len(cells) > 2 else "",
                }
            )
    return rows


def _parse_hk_date(value: str) -> Optional[datetime]:
    try:
        parsed = datetime.strptime(value.strip(), "%d/%m/%Y")
    except ValueError:
        return None
    # Archive rows carry a calendar date without a time; anchor at market
    # local noon so display stays sane, while Today alignment uses the
    # connector's date_only/calendar_date metadata.
    return date_only_market_noon(parsed.date(), HKT)


def _absolute_url(base_url: str, href: str) -> str:
    href = href.strip()
    if href.startswith("http"):
        return href
    if href.startswith("/"):
        return "https://di.hkex.com.hk" + href
    return f"{base_url.rstrip('/')}/{href.lstrip('/')}"


def stable_di_id(url: str, date_text: str, person: str) -> str:
    """Stable fallback id when a DI serial number is unavailable."""
    return hashlib.sha1(
        f"{url}|{date_text}|{person}".encode("utf-8")
    ).hexdigest()


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
