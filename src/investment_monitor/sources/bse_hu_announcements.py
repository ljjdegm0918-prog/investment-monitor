# -*- coding: utf-8 -*-
"""Budapest Stock Exchange official issuer-announcement archive."""

from __future__ import annotations

import json
import os
import re
from datetime import date, datetime
from http.cookiejar import CookieJar
from typing import Any, Iterable, Mapping, Optional, cast
from urllib.parse import urlencode, urljoin
from urllib.request import HTTPCookieProcessor, Request, build_opener
from zoneinfo import ZoneInfo

from ..models import CollectionRequest, InformationItem, MARKET_HU
from ..universe.hu_universe import hu_universe_name_map
from ..web_repository import normalize_hu_ticker
from ._public_disclosure import PublicDisclosureConnector, PublicDisclosureError, clean_html, stable_id

BASE_URL = "https://www.bse.hu"
LIST_URL = BASE_URL + "/issuers_news"
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)


class BseHuDataError(PublicDisclosureError):
    """The official archive returned an invalid or incomplete payload."""


class BseHuClient:
    """Read the BSE archive using its public session-bound paging endpoint."""

    timezone = ZoneInfo("Europe/Budapest")

    def __init__(
        self,
        *,
        opener: Optional[Any] = None,
        max_pages: int = 200,
        timeout: float = 30.0,
    ) -> None:
        if max_pages < 1 or timeout <= 0:
            raise ValueError("BSE page limit and timeout must be positive")
        self._opener = opener or build_opener(HTTPCookieProcessor(CookieJar()))
        self._max_pages = max_pages
        self._timeout = timeout
        self.last_fetch_truncated = False
        self.last_pages_read = 0

    @classmethod
    def from_environment(cls) -> "BseHuClient":
        return cls(
            max_pages=int(os.environ.get("BSE_HU_MAX_PAGES", "200")),
            timeout=float(os.environ.get("BSE_HU_TIMEOUT_SECONDS", "30")),
        )

    def fetch(self, start_date: date, end_date: date) -> Iterable[Mapping[str, Any]]:
        self.last_fetch_truncated = False
        self.last_pages_read = 0
        initial = self._request(Request(LIST_URL, headers=dict(self._headers())))
        csrf = _required_match(initial, r'<meta[^>]+name=["\']_csrf["\'][^>]+content=["\']([^"\']+)', "CSRF token")
        page_path = _required_match(initial, r'var\s+getPageUrl\s*=\s*["\']([^"\']+)', "page URL")
        result_text = _required_match(
            initial,
            r'var\s+result\s*=\s*(\{.*?\})\s*;\s*var\s+getPageUrl',
            "initial result",
            flags=re.S,
        )
        try:
            result = json.loads(result_text)
        except json.JSONDecodeError as error:
            raise BseHuDataError("BSE initial result is not valid JSON") from error
        page_count = _page_count(result)
        seen: set[str] = set()
        reached_start = False

        for page_number in range(1, min(page_count, self._max_pages) + 1):
            if page_number > 1:
                page_url = urljoin(BASE_URL, page_path) + "?" + urlencode({"_csrf": csrf})
                request = Request(
                    page_url,
                    data=json.dumps(page_number).encode("ascii"),
                    headers={**self._headers(), "Content-Type": "application/json", "X-SECURITY": csrf},
                    method="POST",
                )
                text = self._request(request)
                try:
                    result = json.loads(text)
                except json.JSONDecodeError as error:
                    raise BseHuDataError(f"BSE archive page {page_number} is not valid JSON") from error
                if _page_count(result) != page_count:
                    raise BseHuDataError("BSE archive page count changed during pagination")
            self.last_pages_read = page_number
            records = _parse_result(result, LIST_URL)
            if not records and page_number < page_count:
                raise BseHuDataError(f"BSE archive page {page_number} was unexpectedly empty")
            page_ids = {str(record["external_id"]) for record in records}
            if len(page_ids) != len(records) or page_ids & seen:
                raise BseHuDataError(
                    f"BSE archive page {page_number} repeated or overlapped records"
                )
            oldest: Optional[date] = None
            for record in records:
                identifier = str(record["external_id"])
                seen.add(identifier)
                published = record["published_at"]
                day = published.date()
                oldest = day if oldest is None else min(oldest, day)
                if start_date <= day <= end_date:
                    yield record
            if oldest is not None and oldest < start_date:
                reached_start = True
                break

        if page_count > self._max_pages and not reached_start:
            self.last_fetch_truncated = True

    def _request(self, request: Request) -> str:
        try:
            with self._opener.open(request, timeout=self._timeout) as response:
                payload = cast(bytes, response.read())
                return payload.decode("utf-8", errors="replace")
        except (OSError, TimeoutError) as error:
            raise PublicDisclosureError(f"BSE archive request failed: {error}") from error

    @staticmethod
    def _headers() -> Mapping[str, str]:
        return {"Accept": "text/html,application/json;q=0.9,*/*;q=0.8", "User-Agent": USER_AGENT}


def _required_match(text: str, pattern: str, label: str, *, flags: int = 0) -> str:
    match = re.search(pattern, text, flags)
    if not match:
        raise BseHuDataError(f"BSE page is missing {label}")
    return match.group(1)


def _page_count(result: Any) -> int:
    if not isinstance(result, Mapping):
        raise BseHuDataError("BSE archive result is not an object")
    try:
        page_count = int(result["pageCount"])
    except (KeyError, TypeError, ValueError) as error:
        raise BseHuDataError("BSE archive has no valid pageCount") from error
    if page_count < 1 or not isinstance(result.get("items"), list):
        raise BseHuDataError("BSE archive result has an invalid shape")
    return page_count


def _parse_result(result: Mapping[str, Any], retrieval_url: str) -> list[Mapping[str, Any]]:
    records: list[Mapping[str, Any]] = []
    for item in result["items"]:
        if not isinstance(item, Mapping) or not isinstance(item.get("data"), str):
            raise BseHuDataError("BSE archive item has an invalid shape")
        record = _parse_item(item["data"], retrieval_url)
        if record is None:
            raise BseHuDataError("BSE archive item could not be parsed")
        records.append(record)
    return records


def _parse_item(fragment: str, retrieval_url: str) -> Optional[Mapping[str, Any]]:
    pattern = re.compile(
        r'<a[^>]+href=["\'](?P<href>/site/newkib/[^"\']+)["\'][^>]*>'
        r'.{0,1800}?<h2[^>]*class=["\'][^"\']*issuer[^"\']*["\'][^>]*>(?P<issuer>.*?)</h2>'
        r'.{0,1400}?<span[^>]*class=["\'][^"\']*list-date[^"\']*["\'][^>]*>(?P<date>.*?)</span>'
        r'.{0,1400}?<div[^>]*class=["\'][^"\']*title[^"\']*["\'][^>]*>(?P<title>.*?)</div>'
        r'.{0,400}?</a>',
        flags=re.I | re.S,
    )
    match = pattern.search(fragment)
    if not match:
        return None
    raw_date = clean_html(match.group("date"))
    published: Optional[datetime] = None
    for fmt in ("%d %b %Y. %H:%M", "%d %B %Y. %H:%M"):
        try:
            published = datetime.strptime(raw_date, fmt).replace(tzinfo=BseHuClient.timezone)
            break
        except ValueError:
            continue
    if published is None:
        raise BseHuDataError(f"invalid BSE publication date: {raw_date!r}")
    url = urljoin(BASE_URL, match.group("href"))
    native = re.search(r"_(\d+)(?:\D*)$", url)
    return {
        "external_id": f"bse-hu:{native.group(1)}" if native else stable_id("bse-hu", url),
        "issuer": clean_html(match.group("issuer")),
        "published_at": published,
        "published_at_raw": raw_date,
        "published_timezone": "Europe/Budapest",
        "title": clean_html(match.group("title")),
        "document_type": "issuer announcement",
        "url": url,
        "retrieval_url": retrieval_url,
        "raw_payload": fragment,
        "raw_payload_format": "html",
    }


class BseHuAnnouncementsConnector(PublicDisclosureConnector):
    name = "bse_hu_announcements"
    provider = "Budapest Stock Exchange"
    coverage_level = "official_bounded_archive"
    # The archive is market-wide.  Fetch it once for the whole request instead
    # of replaying the same CSRF/session pagination for every requested ticker.
    source_wide_collection = True
    # Preserve official records whose issuer cannot yet be resolved to a
    # reviewed universe identity.  Silent drops would hide a real coverage gap.
    preserve_unmatched_records = True

    def __init__(self, client: Optional[Any] = None, universe: Optional[Mapping[str, Mapping[str, str]]] = None) -> None:
        identities = dict(universe if universe is not None else hu_universe_name_map())
        super().__init__(client=client or BseHuClient.from_environment(), universe=identities, normalizer=normalize_hu_ticker, market=MARKET_HU)
        # hu_universe_name_map also indexes each identity by ISIN.  Expand a
        # source-wide collection only with canonical ticker keys so an
        # off-watchlist but known BSE issuer is resolved instead of becoming
        # a false pending record (and ISIN aliases do not duplicate matches).
        self._canonical_universe_tickers = tuple(sorted({
            normalize_hu_ticker(key)
            for key, identity in identities.items()
            if key.strip().upper() != str(identity.get("isin") or "").strip().upper()
            and normalize_hu_ticker(key)
        }))

    def collect(self, request: CollectionRequest) -> list[InformationItem]:
        requested_hu = tuple(
            ticker for ticker in request.tickers if request.market_for(ticker) == MARKET_HU
        )
        if not requested_hu:
            return super().collect(request)
        expanded_tickers = tuple(dict.fromkeys((*requested_hu, *self._canonical_universe_tickers)))
        expanded_request = CollectionRequest(
            tickers=expanded_tickers,
            start_date=request.start_date,
            end_date=request.end_date,
            markets={ticker: MARKET_HU for ticker in expanded_tickers},
        )
        items = super().collect(expanded_request)
        errors = list(self._last_errors)
        if self.last_unmatched_records:
            errors.append((
                "*",
                f"{self.last_unmatched_records} official BSE record(s) pending issuer matching",
            ))
            self.last_collection_status = "partial"
        if getattr(self._client, "last_fetch_truncated", False):
            message = f"official archive stopped at configured {getattr(self._client, 'last_pages_read', '?')} page limit"
            errors.append(("*", message))
            self.last_collection_status = "partial"
        self._last_errors = tuple(errors)
        return items


__all__ = ["BseHuAnnouncementsConnector", "BseHuClient", "BseHuDataError"]
