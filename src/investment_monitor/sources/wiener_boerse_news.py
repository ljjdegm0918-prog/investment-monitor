# -*- coding: utf-8 -*-
"""Wiener Börse official Ad-hoc News connector.

The public archive is a descending, server-rendered list.  It mixes issuer
Ad-hoc News with exchange/editorial rows, so only structurally valid Ad-hoc
rows are eligible.  Directors' dealings are deliberately excluded from this
issuer-filing connector.  Pagination, ordering and the declared hit count are
validated before a date window can be called complete.
"""

from __future__ import annotations

import html
import math
import re
import time
from dataclasses import dataclass
from datetime import date, datetime, timezone
from typing import Any, Callable, Iterable, List, Mapping, Optional, Sequence, Tuple
from urllib.parse import parse_qs, urlencode, urljoin, urlparse
from zoneinfo import ZoneInfo

from ..models import CollectionRequest, InformationItem, MARKET_AT
from ..provenance import build_raw_provenance
from ..universe.at_universe import at_universe_name_map
from ..web_repository import normalize_at_ticker
from ._public_disclosure import (
    clean_html,
    fetch_text,
    record_matches,
    stable_id,
)

BASE_URL = "https://www.wienerborse.at"
NEWS_URL = BASE_URL + "/en/news-1/"
PAGE_SIZE = 25


class WienerBoerseDataError(RuntimeError):
    """The public archive response could not prove complete collection."""


class WienerBoerseRequestError(RuntimeError):
    """The public archive could not be requested."""


@dataclass(frozen=True)
class WienerNewsPage:
    total: int
    total_pages: int
    active_page: int
    row_keys: Tuple[str, ...]
    timestamps: Tuple[datetime, ...]
    records: Tuple[Mapping[str, Any], ...]
    excluded_non_filings: int


def _native_file_id(url: str) -> Optional[str]:
    query = parse_qs(urlparse(html.unescape(url)).query)
    for key, values in query.items():
        if key.casefold() == "c93603[file]" and values:
            value = str(values[0]).strip()
            if re.fullmatch(r"[A-Za-z0-9_-]{8,80}", value):
                return value
    return None


def _issuer_from_title(title: str) -> str:
    value = re.sub(r"^(?:EQS|PTA)-Adhoc:\s*", "", title, flags=re.I).strip()
    if ":" in value:
        candidate = value.split(":", 1)[0].strip()
        if candidate:
            return candidate
    suffix = re.match(
        r"^(.+?\b(?:AG|SE|Aktiengesellschaft|N\.V\.|NV|GmbH|S\.A\.|SA))\b",
        value,
        flags=re.I,
    )
    return suffix.group(1).strip() if suffix else ""


def _filing_type(title: str) -> str:
    value = title.casefold()
    if any(term in value for term in ("annual report", "annual results", "geschäftsbericht")):
        return "annual_report"
    if any(term in value for term in ("half-year", "half year", "quarter", "results", "ergebnis")):
        return "financial_results"
    if any(term in value for term in ("acquisition", "disposal", "sale of", "übernahme")):
        return "acquisition_disposal"
    if any(term in value for term in ("capital increase", "financing", "bond", "loan", "placement")):
        return "financing"
    if any(term in value for term in ("dividend", "share buyback", "own shares")):
        return "dividend" if "dividend" in value else "share_buyback"
    if any(term in value for term in ("management board", "supervisory board", "resign", "appoint")):
        return "management_change"
    return "material_change"


def parse_wiener_news_page(text: str, retrieval_url: str) -> WienerNewsPage:
    """Parse every visible row, retaining only eligible issuer filings."""
    visible = clean_html(text).casefold()
    if any(marker in visible for marker in ("access denied", "loading...", "service unavailable")):
        raise WienerBoerseDataError("Wiener Börse returned an access/loading page")
    if 'data-sxp-ajax-snippet="c93603-adhoc-news"' not in text:
        raise WienerBoerseDataError("Wiener Börse news archive container is missing")
    total_match = re.search(
        r"Your search resulted in\s*<b>\s*([0-9,]+)\s*</b>\s*hits",
        text,
        flags=re.I | re.S,
    )
    if not total_match:
        raise WienerBoerseDataError("Wiener Börse hit count is missing")
    total = int(total_match.group(1).replace(",", ""))
    total_pages = max(1, math.ceil(total / PAGE_SIZE))
    active_match = re.search(
        r'<li\b[^>]*class=["\'][^"\']*active[^"\']*["\'][^>]*>\s*'
        r'<a\b[^>]*data-page=["\'](\d+)["\']',
        text,
        flags=re.I | re.S,
    )
    if not active_match:
        raise WienerBoerseDataError("Wiener Börse active page marker is missing")
    active_page = int(active_match.group(1)) + 1

    blocks = text.split('<div class="news-row">')[1:]
    if total > 0 and not blocks:
        raise WienerBoerseDataError("Wiener Börse declared hits but returned no news rows")
    row_keys: List[str] = []
    timestamps: List[datetime] = []
    records: List[Mapping[str, Any]] = []
    excluded = 0
    for block in blocks:
        block = block.split('<div class="news-row">', 1)[0]
        datetime_match = re.search(
            r'<div\b[^>]*class=["\'][^"\']*datetime[^"\']*["\'][^>]*>(.*?)</div>',
            block,
            flags=re.I | re.S,
        )
        link_match = re.search(
            r'<div\b[^>]*class=["\'][^"\']*header-shorten[^"\']*["\'][^>]*>'
            r'.*?<a\b[^>]*href=["\']([^"\']+)["\'][^>]*>(.*?)</a>',
            block,
            flags=re.I | re.S,
        )
        if not datetime_match or not link_match:
            raise WienerBoerseDataError("Wiener Börse news row markup changed")
        kind_date = clean_html(datetime_match.group(1))
        kind_match = re.fullmatch(
            r"(.+?)\s*[·]\s*(\d{2}/\d{2}/\d{4},\s*\d{2}:\d{2}:\d{2})",
            kind_date,
        )
        if not kind_match:
            raise WienerBoerseDataError(f"Wiener Börse row date/type changed: {kind_date!r}")
        kind = kind_match.group(1).strip()
        raw_date = kind_match.group(2)
        try:
            published = datetime.strptime(raw_date, "%m/%d/%Y, %H:%M:%S").replace(
                tzinfo=ZoneInfo("Europe/Vienna")
            )
        except ValueError as error:
            raise WienerBoerseDataError(f"Wiener Börse row date is invalid: {raw_date!r}") from error
        raw_url = urljoin(BASE_URL, html.unescape(link_match.group(1)))
        title = clean_html(link_match.group(2))
        if not title:
            raise WienerBoerseDataError("Wiener Börse news row title is empty")
        native_id = _native_file_id(raw_url)
        row_key = (
            f"file:{native_id}"
            if native_id
            else stable_id("wiener-news-row", f"{kind}|{raw_date}|{raw_url}|{title}")
        )
        row_keys.append(row_key)
        timestamps.append(published)
        if kind.casefold() != "ad-hoc news":
            excluded += 1
            continue
        if re.match(r"^(?:EQS|PTA)-DD:", title, flags=re.I) or "director's dealing" in title.casefold():
            excluded += 1
            continue
        if native_id is None:
            raise WienerBoerseDataError("Wiener Börse Ad-hoc row has no opaque file id")
        official_url = NEWS_URL + "?" + urlencode({"c93603[file]": native_id})
        issuer = _issuer_from_title(title)
        records.append(
            {
                "external_id": f"wiener-boerse:{native_id}",
                "native_id": native_id,
                "issuer": issuer,
                "published_at": published,
                "published_at_raw": raw_date,
                "published_timezone": "Europe/Vienna",
                "title": title,
                "document_type": _filing_type(title),
                "classification_code": "ad_hoc_news",
                "url": official_url,
                "attachments": [official_url],
                "document_format": "pdf_or_official_file",
                "retrieval_url": retrieval_url,
                "raw_payload": block,
                "raw_payload_format": "html",
            }
        )
    if total == 0 and (row_keys or records):
        raise WienerBoerseDataError("Wiener Börse declared zero hits but returned rows")
    return WienerNewsPage(
        total=total,
        total_pages=total_pages,
        active_page=active_page,
        row_keys=tuple(row_keys),
        timestamps=tuple(timestamps),
        records=tuple(records),
        excluded_non_filings=excluded,
    )


def _parse_page(text: str, retrieval_url: str) -> Sequence[Mapping[str, Any]]:
    """Backward-compatible record-only parser used by earlier callers."""
    return parse_wiener_news_page(text, retrieval_url).records


class WienerBoerseClient:
    timezone = ZoneInfo("Europe/Vienna")

    def __init__(
        self,
        *,
        fetcher: Callable[[str], Any] = fetch_text,
        max_pages: int = 50,
        page_delay: float = 0.1,
        sleeper: Callable[[float], None] = time.sleep,
    ) -> None:
        if max_pages < 1:
            raise ValueError("max_pages must be positive")
        self._fetcher = fetcher
        self._max_pages = max_pages
        self._page_delay = max(0.0, page_delay)
        self._sleeper = sleeper
        self.last_excluded_non_filings = 0

    @staticmethod
    def _url(page: int) -> str:
        return f"{NEWS_URL}?{urlencode({'c93603-page': page, 'per-page': PAGE_SIZE})}"

    def _read(self, url: str) -> str:
        try:
            response = self._fetcher(url)
        except Exception as error:
            raise WienerBoerseRequestError(f"Wiener Börse request failed: {url}: {error}") from error
        if isinstance(response, tuple):
            response = response[0]
        if not isinstance(response, str):
            raise WienerBoerseRequestError("Wiener Börse fetcher returned non-text data")
        return response

    def fetch(self, start_date: date, end_date: date) -> Iterable[Mapping[str, Any]]:
        if end_date < start_date:
            raise ValueError("end_date must not precede start_date")
        self.last_excluded_non_filings = 0
        seen: set[str] = set()
        prior_oldest: Optional[datetime] = None
        declared_total: Optional[int] = None
        declared_pages: Optional[int] = None
        collected: List[Mapping[str, Any]] = []
        for page_number in range(1, self._max_pages + 1):
            if page_number > 1 and self._page_delay:
                self._sleeper(self._page_delay)
            url = self._url(page_number)
            page = parse_wiener_news_page(self._read(url), url)
            if declared_total is None:
                declared_total, declared_pages = page.total, page.total_pages
                if declared_pages > self._max_pages:
                    raise WienerBoerseDataError(
                        f"Wiener Börse archive needs {declared_pages} pages; max_pages={self._max_pages}"
                    )
            if page.total != declared_total or page.total_pages != declared_pages:
                raise WienerBoerseDataError("Wiener Börse hit count changed during pagination")
            if page.active_page != page_number:
                raise WienerBoerseDataError(
                    f"Wiener Börse returned page {page.active_page} for request {page_number}"
                )
            expected_rows = min(PAGE_SIZE, max(0, page.total - (page_number - 1) * PAGE_SIZE))
            if len(page.row_keys) != expected_rows:
                raise WienerBoerseDataError(
                    f"Wiener Börse page {page_number} row count mismatch: "
                    f"expected={expected_rows} actual={len(page.row_keys)}"
                )
            if len(set(page.row_keys)) != len(page.row_keys) or seen.intersection(page.row_keys):
                raise WienerBoerseDataError(
                    f"Wiener Börse pagination repeated/overlapped page {page_number}"
                )
            if any(
                page.timestamps[index] < page.timestamps[index + 1]
                for index in range(len(page.timestamps) - 1)
            ):
                raise WienerBoerseDataError(f"Wiener Börse page {page_number} is not descending")
            if page.timestamps:
                newest, oldest = max(page.timestamps), min(page.timestamps)
                if prior_oldest is not None and newest > prior_oldest:
                    raise WienerBoerseDataError(
                        f"Wiener Börse pagination date order regressed on page {page_number}"
                    )
                prior_oldest = oldest
            seen.update(page.row_keys)
            self.last_excluded_non_filings += page.excluded_non_filings
            for record in page.records:
                local_day = record["published_at"].astimezone(self.timezone).date()
                if start_date <= local_day <= end_date:
                    collected.append(record)
            if page.total == 0:
                return ()
            oldest_day = min(page.timestamps).astimezone(self.timezone).date()
            if oldest_day < start_date:
                return tuple(collected)
            if page_number == page.total_pages:
                if oldest_day > start_date:
                    raise WienerBoerseDataError(
                        "Wiener Börse rolling archive does not reach the requested start date"
                    )
                return tuple(collected)
        raise WienerBoerseDataError(
            f"Wiener Börse pagination reached max_pages={self._max_pages}"
        )


class WienerBoerseNewsConnector:
    name = "wiener_boerse_news"
    provider = "Wiener Börse Ad-hoc News"
    max_lookback_days = 30
    coverage_level = "official_exchange_ad_hoc_rolling_30d"

    def __init__(
        self,
        client: Optional[WienerBoerseClient] = None,
        universe: Optional[Mapping[str, Mapping[str, str]]] = None,
    ) -> None:
        self._client = client or WienerBoerseClient()
        self._universe = dict(universe if universe is not None else at_universe_name_map())
        self._last_errors: Tuple[Tuple[str, str], ...] = ()
        self.last_collection_status = "empty"
        self.last_records_read = 0
        self.last_unmatched_records = 0
        self.last_pending_records: Tuple[Mapping[str, Any], ...] = ()
        self.last_excluded_non_filings = 0

    @property
    def last_errors(self) -> Tuple[Tuple[str, str], ...]:
        return self._last_errors

    def collect(self, request: CollectionRequest) -> List[InformationItem]:
        tickers = tuple(
            dict.fromkeys(
                normalize_at_ticker(ticker)
                for ticker in request.tickers
                if request.market_for(ticker) == MARKET_AT
            )
        )
        if not tickers:
            self._reset("empty")
            return []
        try:
            records = tuple(self._client.fetch(request.start_date, request.end_date))
        except Exception as error:
            message = str(error) or error.__class__.__name__
            self._last_errors = (("*", message),)
            self.last_collection_status = "unavailable"
            self.last_records_read = 0
            self.last_unmatched_records = 0
            self.last_pending_records = ()
            self.last_excluded_non_filings = int(
                getattr(self._client, "last_excluded_non_filings", 0)
            )
            raise WienerBoerseRequestError(message) from error
        self.last_records_read = len(records)
        self.last_excluded_non_filings = int(
            getattr(self._client, "last_excluded_non_filings", 0)
        )
        pending = []
        items: List[InformationItem] = []
        collected_at = datetime.now(timezone.utc)
        for record in records:
            matched = tuple(
                ticker
                for ticker in tickers
                if record_matches(
                    record,
                    ticker,
                    self._universe.get(ticker, {}),
                    normalize_at_ticker,
                )
            )
            if not matched:
                pending.append(
                    {
                        "external_id": record.get("external_id"),
                        "issuer": record.get("issuer"),
                        "title": record.get("title"),
                        "published_at": record.get("published_at"),
                        "url": record.get("url"),
                        "match_status": "pending_matching",
                    }
                )
            identity = self._universe.get(matched[0], {}) if matched else {}
            native_id = str(record.get("native_id") or "")
            source_url = str(record["url"])
            attachments = list(record.get("attachments") or [])
            items.append(
                InformationItem(
                    source=self.name,
                    source_type="regulatory_filing",
                    external_id=str(record["external_id"]),
                    tickers=matched,
                    issuer=str(
                        record.get("issuer")
                        or identity.get("name")
                        or (matched[0] if matched else "Unmatched issuer")
                    ),
                    published_at=record["published_at"],
                    title=str(record["title"]),
                    document_type=str(record["document_type"]),
                    url=source_url,
                    collected_at=collected_at,
                    raw_metadata={
                        **build_raw_provenance(
                            official_source_id=native_id,
                            official_source_url=source_url,
                            retrieval_url=str(record.get("retrieval_url") or ""),
                            raw_payload=record.get("raw_payload") or record,
                            raw_payload_format="html",
                            classification_code="ad_hoc_news",
                            classification_label="Wiener Börse Ad-hoc News",
                            published_at_raw=str(record.get("published_at_raw") or ""),
                            published_timezone="Europe/Vienna",
                        ),
                        "source_tier": 1,
                        "source_tier_label": "exchange_official",
                        "exchange": "Wiener Börse",
                        "official_document": True,
                        "officiality": "official_exchange_archive",
                        "wiener_file_id": native_id,
                        "isin": str(identity.get("isin") or "") or None,
                        "match_status": "matched" if matched else "pending_matching",
                        "identity_candidates": {
                            "issuer": str(record.get("issuer") or "") or None,
                            "isin": None,
                            "ticker": None,
                        },
                        "attachments": attachments,
                        "attachment_urls": attachments,
                        "document_format": record.get("document_format"),
                        "coverage_level": self.coverage_level,
                    },
                    market=MARKET_AT,
                    summary=None,
                    effective_at=record["published_at"],
                )
            )
        self._last_errors = ()
        self.last_pending_records = tuple(pending)
        self.last_unmatched_records = len(pending)
        self.last_collection_status = (
            "partial" if pending else "success" if items else "empty"
        )
        return items

    def _reset(self, status: str) -> None:
        self._last_errors = ()
        self.last_collection_status = status
        self.last_records_read = 0
        self.last_unmatched_records = 0
        self.last_pending_records = ()
        self.last_excluded_non_filings = 0


__all__ = [
    "PAGE_SIZE",
    "WienerBoerseClient",
    "WienerBoerseDataError",
    "WienerBoerseNewsConnector",
    "WienerBoerseRequestError",
    "WienerNewsPage",
    "_parse_page",
    "parse_wiener_news_page",
]
