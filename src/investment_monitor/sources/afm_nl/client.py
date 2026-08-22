"""Strict reader for the AFM public inside-information register.

The endpoint is the public pagination endpoint used by the AFM register page.
It returns server-rendered HTML, including an explicit result total.  The
client reconciles that total against every unique AFM record id and fails
closed on suspicious empty pages, overlap, drift, or markup changes.
"""

from __future__ import annotations

import html
import math
import re
import time
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any, Callable, Iterable, Mapping, Optional, Sequence, Tuple
from urllib.parse import parse_qs, urlencode, urljoin, urlparse
from zoneinfo import ZoneInfo

from .._public_disclosure import clean_html, fetch_text

AFM_BASE_URL = "https://www.afm.nl"
AFM_REGISTER_URL = (
    AFM_BASE_URL
    + "/en/sector/registers/meldingenregisters/openbaarmaking-voorwetenschap"
)
AFM_PAGED_URL = AFM_BASE_URL + "/api/sitecore/RegisterOverview/PagedRegisters"
AFM_CONTEXT_ID = "{6122672C-938A-4AA6-A244-80B2631E4AEF}"
AFM_PAGE_SIZE = 50

_DUTCH_MONTHS = {
    "jan": 1,
    "feb": 2,
    "mrt": 3,
    "apr": 4,
    "mei": 5,
    "jun": 6,
    "jul": 7,
    "aug": 8,
    "sep": 9,
    "okt": 10,
    "nov": 11,
    "dec": 12,
}
_RESULT_ROW = re.compile(
    r'<tr\b[^>]*class=["\'][^"\']*'
    r'jq_registers_register-paged-list_results_tr[^"\']*["\'][^>]*>'
    r'(.*?)</tr>',
    re.I | re.S,
)


class AfmNlRequestError(RuntimeError):
    """The AFM public endpoint could not be requested."""


class AfmNlDataError(RuntimeError):
    """The AFM response could not prove complete, valid collection."""


@dataclass(frozen=True)
class AfmPage:
    total: int
    page_size: int
    active_page: int
    date_from: str
    date_till: str
    records: Tuple[Mapping[str, Any], ...]


def _parse_dutch_datetime(value: str) -> datetime:
    match = re.fullmatch(
        r"\s*(\d{1,2})\s+([A-Za-z]{3})\s+(\d{4})\s*-\s*"
        r"(\d{1,2}):(\d{2})\s*",
        value,
    )
    if not match:
        raise AfmNlDataError(f"AFM row has an unparseable date: {value!r}")
    month = _DUTCH_MONTHS.get(match.group(2).casefold())
    if month is None:
        raise AfmNlDataError(f"AFM row has an unknown Dutch month: {value!r}")
    try:
        return datetime(
            int(match.group(3)),
            month,
            int(match.group(1)),
            int(match.group(4)),
            int(match.group(5)),
            tzinfo=ZoneInfo("Europe/Amsterdam"),
        )
    except ValueError as error:
        raise AfmNlDataError(f"AFM row has an invalid date: {value!r}") from error


def _attribute(text: str, name: str) -> Optional[str]:
    match = re.search(
        rf"\b{re.escape(name)}=[\"']([^\"']*)[\"']",
        text,
        flags=re.I,
    )
    return html.unescape(match.group(1)) if match else None


def parse_afm_page(text: str, retrieval_url: str) -> AfmPage:
    """Parse one AFM result fragment and reject ambiguous empty payloads."""
    visible = clean_html(text).casefold()
    if any(marker in visible for marker in ("access denied", "sign in", "loading...")):
        raise AfmNlDataError("AFM returned an access/loading page")

    root_match = re.search(
        r'<div\b[^>]*id=["\']registers_register-paged-list_div["\'][^>]*>',
        text,
        flags=re.I,
    )
    if not root_match:
        raise AfmNlDataError("AFM register root is missing")
    root = root_match.group(0)
    context = _attribute(root, "data-context-item-id")
    if context != AFM_CONTEXT_ID:
        raise AfmNlDataError(f"AFM register context changed: {context!r}")
    try:
        page_size = int(_attribute(root, "data-page-size") or "")
    except ValueError as error:
        raise AfmNlDataError("AFM page size is invalid") from error
    if page_size != AFM_PAGE_SIZE:
        raise AfmNlDataError(f"AFM page size changed: {page_size}")
    date_from = str(_attribute(root, "data-date-from") or "")
    date_till = str(_attribute(root, "data-date-till") or "")

    total_match = re.search(
        r'class=["\'][^"\']*cc-em--table__results[^"\']*["\'][^>]*>'
        r'.*?<strong>\s*([0-9.,]+)\s*</strong>',
        text,
        flags=re.I | re.S,
    )
    if not total_match:
        raise AfmNlDataError("AFM result total is missing")
    try:
        total = int(total_match.group(1).replace(".", "").replace(",", ""))
    except ValueError as error:
        raise AfmNlDataError("AFM result total is invalid") from error

    table_match = re.search(
        r'<table\b[^>]*data-register-view=["\']register-overview-paged-list["\']'
        r'[^>]*>(.*?)</table>',
        text,
        flags=re.I | re.S,
    )
    if not table_match:
        raise AfmNlDataError("AFM result table is missing")

    active_match = re.search(
        r'class=["\'][^"\']*cc-pagination__link--active[^"\']*["\']'
        r'[^>]*data-page-number=["\'](\d+)["\']',
        text,
        flags=re.I,
    )
    if not active_match:
        active_match = re.search(
            r'data-page-number=["\'](\d+)["\'][^>]*class=["\']'
            r'[^"\']*cc-pagination__link--active',
            text,
            flags=re.I,
        )
    if not active_match:
        raise AfmNlDataError("AFM active page marker is missing")
    active_page = int(active_match.group(1))

    records = []
    for row in _RESULT_ROW.findall(table_match.group(1)):
        cells = re.findall(r"<td\b[^>]*>(.*?)</td>", row, flags=re.I | re.S)
        if len(cells) != 3:
            raise AfmNlDataError("AFM result row column count changed")
        link_match = re.search(r'<a\b[^>]*href=["\']([^"\']+)["\']', cells[0], re.I)
        if not link_match:
            raise AfmNlDataError("AFM result row is missing its official detail link")
        raw_href = html.unescape(link_match.group(1))
        query = parse_qs(urlparse(raw_href).query)
        native_id = str((query.get("id") or [""])[0]).strip()
        if not re.fullmatch(r"C\d{4}-\d{5}", native_id, flags=re.I):
            raise AfmNlDataError(f"AFM result row has an invalid id: {native_id!r}")
        raw_date = clean_html(cells[0])
        issuer = clean_html(cells[1])
        title = clean_html(cells[2])
        if not issuer or not title:
            raise AfmNlDataError("AFM result row is missing issuer or title")
        published = _parse_dutch_datetime(raw_date)
        official_url = f"{AFM_REGISTER_URL}/details?{urlencode({'id': native_id})}"
        records.append(
            {
                "external_id": f"afm:{native_id.upper()}",
                "native_id": native_id.upper(),
                "issuer": issuer,
                "published_at": published,
                "published_at_raw": raw_date,
                "published_timezone": "Europe/Amsterdam",
                "title": title,
                "document_type": "inside_information",
                "classification_code": "mar_article_17",
                "url": official_url,
                "retrieval_url": retrieval_url,
                "raw_payload": row,
                "raw_payload_format": "html",
            }
        )

    if total == 0 and records:
        raise AfmNlDataError("AFM declared zero results but returned rows")
    if total > 0 and not records:
        raise AfmNlDataError("AFM declared results but returned an empty page")
    return AfmPage(
        total=total,
        page_size=page_size,
        active_page=active_page,
        date_from=date_from,
        date_till=date_till,
        records=tuple(records),
    )


class AfmNlClient:
    """Collect an exact date range from the official AFM public register."""

    timezone = ZoneInfo("Europe/Amsterdam")

    def __init__(
        self,
        *,
        fetcher: Callable[[str], Any] = fetch_text,
        max_pages: int = 200,
        page_delay: float = 0.1,
        sleeper: Callable[[float], None] = time.sleep,
    ) -> None:
        if max_pages < 1:
            raise ValueError("max_pages must be positive")
        self._fetcher = fetcher
        self._max_pages = max_pages
        self._page_delay = max(0.0, page_delay)
        self._sleeper = sleeper

    @staticmethod
    def _date_param(value: date) -> str:
        return value.strftime("%d-%m-%Y")

    def _url(self, page: int, start_date: date, end_date: date) -> str:
        params = {
            "contextItemId": AFM_CONTEXT_ID,
            "skip": (page - 1) * AFM_PAGE_SIZE,
            "take": AFM_PAGE_SIZE,
            "currentPage": page,
            "filter1": "",
            "filter2": "",
            "keywords": "",
            "dateFrom": self._date_param(start_date),
            "dateTill": self._date_param(end_date),
        }
        return f"{AFM_PAGED_URL}?{urlencode(params)}"

    def _read(self, url: str) -> str:
        try:
            response = self._fetcher(url)
        except Exception as error:
            raise AfmNlRequestError(f"AFM request failed: {url}: {error}") from error
        if isinstance(response, tuple):
            response = response[0]
        if not isinstance(response, str):
            raise AfmNlRequestError("AFM fetcher returned a non-text response")
        return response

    def fetch(self, start_date: date, end_date: date) -> Iterable[Mapping[str, Any]]:
        if end_date < start_date:
            raise ValueError("end_date must not precede start_date")
        expected_from = self._date_param(start_date)
        expected_till = self._date_param(end_date)
        first_url = self._url(1, start_date, end_date)
        first = parse_afm_page(self._read(first_url), first_url)
        pages = max(1, math.ceil(first.total / AFM_PAGE_SIZE))
        if pages > self._max_pages:
            raise AfmNlDataError(
                f"AFM result total requires {pages} pages; max_pages={self._max_pages}"
            )

        seen: set[str] = set()
        collected = []
        for page_number in range(1, pages + 1):
            if page_number == 1:
                page = first
            else:
                if self._page_delay:
                    self._sleeper(self._page_delay)
                url = self._url(page_number, start_date, end_date)
                page = parse_afm_page(self._read(url), url)
            if page.total != first.total:
                raise AfmNlDataError(
                    f"AFM result total changed on page {page_number}: "
                    f"{first.total} -> {page.total}"
                )
            if page.date_from != expected_from or page.date_till != expected_till:
                raise AfmNlDataError(
                    f"AFM date filter changed on page {page_number}"
                )
            if page.active_page != page_number:
                raise AfmNlDataError(
                    f"AFM returned active page {page.active_page} for request {page_number}"
                )
            expected_rows = min(
                AFM_PAGE_SIZE,
                max(0, first.total - (page_number - 1) * AFM_PAGE_SIZE),
            )
            if len(page.records) != expected_rows:
                raise AfmNlDataError(
                    f"AFM page {page_number} row count mismatch: "
                    f"expected={expected_rows} actual={len(page.records)}"
                )
            for record in page.records:
                identifier = str(record["external_id"])
                if identifier in seen:
                    raise AfmNlDataError(
                        f"AFM pagination repeated record {identifier} on page {page_number}"
                    )
                seen.add(identifier)
                published = record["published_at"]
                if not start_date <= published.astimezone(self.timezone).date() <= end_date:
                    raise AfmNlDataError(
                        f"AFM returned {identifier} outside the requested date window"
                    )
                collected.append(record)
        if len(collected) != first.total:
            raise AfmNlDataError(
                f"AFM total reconciliation failed: declared={first.total} actual={len(collected)}"
            )
        return tuple(collected)


__all__ = [
    "AFM_CONTEXT_ID",
    "AFM_PAGE_SIZE",
    "AFM_PAGED_URL",
    "AFM_REGISTER_URL",
    "AfmNlClient",
    "AfmNlDataError",
    "AfmNlRequestError",
    "AfmPage",
    "parse_afm_page",
]
