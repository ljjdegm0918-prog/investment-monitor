# -*- coding: utf-8 -*-
"""Official Norwegian NewsWeb and Euronext Lisbon disclosures."""

from __future__ import annotations

import re
import time
from datetime import date, datetime, timedelta
from typing import Any, Callable, Iterable, Mapping, Optional, Sequence, Tuple
from urllib.parse import urlencode
from zoneinfo import ZoneInfo

from ..models import MARKET_NO, MARKET_PT
from ..universe.no_universe import no_universe_name_map
from ..universe.pt_universe import pt_universe_name_map
from ..web_repository import normalize_no_ticker, normalize_pt_ticker
from ._public_disclosure import (
    PublicDisclosureConnector,
    PublicDisclosureError,
    clean_html,
    fetch_json,
    fetch_text,
)

NEWSWEB_API = "https://api3.oslo.oslobors.no/v1/newsreader/list"
NEWSWEB_DETAIL_API = "https://api3.oslo.oslobors.no/v1/newsreader/message"
NEWSWEB_ATTACHMENT_API = "https://api3.oslo.oslobors.no/v1/newsreader/attachment"
NEWSWEB_PAGE = "https://newsweb.oslobors.no/message/"
NEWSWEB_MARKETS = ("XOSL", "XOAX", "XOAM", "MERK")
LISBON_ARCHIVE = (
    "https://live.euronext.com/en/listview/"
    "company-press-releases-by-mkt-arch/406/all"
)
NEWSWEB_HEADERS = {"Origin": "https://newsweb.no", "Referer": "https://newsweb.no/"}
LISBON_FILING_TOPIC_MARKERS = (
    "annual financial", "audit report", "half yearly", "quarterly",
    "inside information", "major shareholding", "own shares",
    "additional regulated information", "adjustment of interest rate",
    "change in capital", "changes in the rights", "corporate life",
    "dividend", "general meeting", "home member state", "voting rights",
    "financial report", "governance",
)


def _lisbon_is_filing_topic(value: str) -> bool:
    normalized = clean_html(value).casefold()
    return any(marker in normalized for marker in LISBON_FILING_TOPIC_MARKERS)


class NewswebClient:
    timezone = ZoneInfo("Europe/Oslo")

    def __init__(
        self,
        *,
        sleeper: Callable[[float], None] = time.sleep,
        request_interval: float = 0.1,
    ) -> None:
        self._sleeper = sleeper
        self.request_interval = max(0.0, request_interval)
        self._request_count = 0

    def _throttle(self) -> None:
        if self._request_count and self.request_interval:
            self._sleeper(self.request_interval)
        self._request_count += 1

    def fetch(self, start_date: date, end_date: date) -> Iterable[Mapping[str, Any]]:
        self._request_count = 0
        seen = set()
        for market in NEWSWEB_MARKETS:
            for record in self._fetch_window(market, start_date, end_date):
                identifier = self._required_id(record, "messageId")
                if identifier in seen:
                    continue
                seen.add(identifier)
                detail, detail_url = self._detail(identifier)
                raw_time = self._required_text(detail, "publishedTime")
                published = self._published_at(raw_time)
                categories = detail.get("category")
                if isinstance(categories, Mapping):
                    categories = [categories]
                if not isinstance(categories, list) or any(
                    not isinstance(item, Mapping) for item in categories
                ):
                    raise PublicDisclosureError(
                        f"NewsWeb message {identifier} has invalid category"
                    )
                labels = [
                    str(item.get("category_en") or item.get("category_no") or item.get("id") or "")
                    for item in categories
                ]
                attachments = self._attachments(detail, identifier)
                correction_for = str(detail.get("correctionForMessageId") or "")
                corrected_by = str(detail.get("correctedByMessageId") or "")
                yield {
                    "external_id": f"newsweb:{identifier}",
                    "ticker": detail.get("issuerSign"),
                    "issuer": detail.get("issuerName") or detail.get("issuerSign"),
                    "published_at": published,
                    "published_at_raw": raw_time,
                    "published_timezone": "UTC",
                    "title": str(detail.get("title") or "Untitled disclosure"),
                    "document_type": ", ".join(filter(None, labels)) or "NewsWeb disclosure",
                    "classification_code": ",".join(
                        str(item.get("id") or "") for item in categories if isinstance(item, Mapping)
                    ),
                    "url": NEWSWEB_PAGE + identifier,
                    "retrieval_url": detail_url,
                    "raw_payload": detail,
                    "raw_payload_format": "json",
                    "revision_semantics": (
                        f"correctionForMessageId={correction_for or '0'}; "
                        f"correctedByMessageId={corrected_by or '0'}"
                    ),
                    "attachments": attachments,
                    "summary": str(detail.get("body") or "") or None,
                }

    def _fetch_window(self, market: str, start: date, end: date) -> Sequence[Mapping[str, Any]]:
        query = urlencode({
            "category": "", "issuer": "", "fromDate": start.isoformat(),
            "toDate": end.isoformat(), "market": market, "messageTitle": "",
        })
        self._throttle()
        payload, _ = fetch_json(
            f"{NEWSWEB_API}?{query}",
            payload={},
            headers=NEWSWEB_HEADERS,
        )
        data = payload.get("data") if isinstance(payload, Mapping) else None
        if not isinstance(data, Mapping) or not isinstance(data.get("messages"), list):
            raise PublicDisclosureError("NewsWeb response has no data.messages")
        if not isinstance(data.get("overflow"), bool):
            raise PublicDisclosureError("NewsWeb response has invalid overflow flag")
        if any(not isinstance(item, Mapping) for item in data["messages"]):
            raise PublicDisclosureError("NewsWeb response has invalid message row")
        if data["overflow"]:
            if start >= end:
                raise PublicDisclosureError(f"NewsWeb overflow for {market} on {start}")
            midpoint = start + timedelta(days=(end - start).days // 2)
            return [
                *self._fetch_window(market, start, midpoint),
                *self._fetch_window(market, midpoint + timedelta(days=1), end),
            ]
        return list(data["messages"])

    def _detail(self, message_id: str) -> tuple[Mapping[str, Any], str]:
        url = NEWSWEB_DETAIL_API + "?" + urlencode({"messageId": message_id})
        self._throttle()
        payload, _ = fetch_json(url, payload={}, headers=NEWSWEB_HEADERS)
        data = payload.get("data") if isinstance(payload, Mapping) else None
        message = data.get("message") if isinstance(data, Mapping) else None
        if not isinstance(message, Mapping):
            raise PublicDisclosureError("NewsWeb detail response has no data.message")
        if self._required_id(message, "messageId") != message_id:
            raise PublicDisclosureError("NewsWeb detail messageId does not match request")
        return message, url

    @staticmethod
    def _required_text(record: Mapping[str, Any], field: str) -> str:
        value = str(record.get(field) or "").strip()
        if not value:
            raise PublicDisclosureError(f"NewsWeb message is missing {field}")
        return value

    @classmethod
    def _required_id(cls, record: Mapping[str, Any], field: str) -> str:
        return cls._required_text(record, field)

    @staticmethod
    def _published_at(value: str) -> datetime:
        try:
            published = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError as error:
            raise PublicDisclosureError(f"NewsWeb has invalid publishedTime {value!r}") from error
        if published.tzinfo is None:
            raise PublicDisclosureError("NewsWeb publishedTime is missing a timezone")
        return published

    @staticmethod
    def _attachments(message: Mapping[str, Any], message_id: str) -> list[str]:
        count = message.get("numbAttachments")
        if not isinstance(count, int) or count < 0:
            raise PublicDisclosureError(
                f"NewsWeb message {message_id} has invalid numbAttachments"
            )
        rows = message.get("attachments")
        if rows is None and count == 0:
            return []
        if not isinstance(rows, list) or len(rows) != count:
            raise PublicDisclosureError(
                f"NewsWeb message {message_id} attachment list does not match count"
            )
        attachments = []
        for row in rows:
            if not isinstance(row, Mapping):
                raise PublicDisclosureError(f"NewsWeb message {message_id} has invalid attachment")
            attachment_id = NewswebClient._required_id(row, "id")
            attachments.append(
                NEWSWEB_ATTACHMENT_API + "?" + urlencode({
                    "messageId": message_id,
                    "attachmentId": attachment_id,
                })
            )
        return attachments


def _lisbon_records(text: str, retrieval_url: str) -> Sequence[Mapping[str, Any]]:
    if re.search(r"(?:access denied|captcha|cloudflare|login form)", text, re.I):
        raise PublicDisclosureError("Euronext Lisbon returned a WAF/login page")
    records = []
    candidate_rows = [
        row
        for row in re.findall(r"<tr\b[^>]*>(.*?)</tr>", text, flags=re.I | re.S)
        if "standardRightCompanyPressRelease" in row
    ]
    if not candidate_rows:
        if re.search(
            r'class=["\'][^"\']*view-empty[^"\']*["\'][\s\S]*?'
            r'no results match your search criteria',
            text,
            flags=re.I,
        ):
            return []
        raise PublicDisclosureError(
            "Euronext Lisbon page has neither disclosure rows nor an explicit empty marker"
        )
    for row in candidate_rows:
        node_match = re.search(r'data-node-nid=["\'](\d+)', row, flags=re.I)
        title_match = re.search(
            r'<a[^>]*class=["\'][^"\']*standardRightCompanyPressRelease[^"\']*["\'][^>]*>(.*?)</a>',
            row, flags=re.I | re.S,
        )
        company_match = re.search(
            r'<td[^>]*field-company-name[^>]*>(.*?)</td>', row, flags=re.I | re.S
        )
        date_match = re.search(
            r'field-company-pr-pub-datetime[^>]*>(.*?)</td>', row, flags=re.I | re.S
        )
        if not (node_match and title_match and company_match and date_match):
            raise PublicDisclosureError("Euronext Lisbon disclosure row has changed structure")
        raw_date = clean_html(date_match.group(1))
        parsed = None
        date_without_zone = re.sub(r"\s+[A-Z]{3,5}$", "", raw_date)
        for fmt in ("%d %b %Y %H:%M", "%d %B %Y %H:%M"):
            try:
                parsed = datetime.strptime(date_without_zone, fmt).replace(tzinfo=ZoneInfo("Europe/Lisbon"))
                break
            except ValueError:
                pass
        if parsed is None:
            raise PublicDisclosureError(
                f"Euronext Lisbon has invalid publication time {raw_date!r}"
            )
        node = node_match.group(1)
        detail_url = f"https://live.euronext.com/en/listview/company-press-release/{node}"
        topic_match = re.search(
            r'views-field-field-company-press-releases[^>]*>(.*?)</td>',
            row,
            flags=re.I | re.S,
        )
        topic = clean_html(topic_match.group(1)) if topic_match else ""
        records.append({
            "external_id": f"euronext-lisbon:{node}",
            "issuer": clean_html(company_match.group(1)),
            "published_at": parsed,
            "published_at_raw": raw_date,
            "published_timezone": "Europe/Lisbon",
            "title": clean_html(title_match.group(1)),
            "document_type": topic or "unclassified company press release",
            "classification_code": (
                "official_filing" if _lisbon_is_filing_topic(topic)
                else "non_filing_press_release"
            ),
            "url": detail_url,
            "retrieval_url": retrieval_url,
            "raw_payload": row,
            "raw_payload_format": "html",
        })
    return records


class EuronextLisbonClient:
    timezone = ZoneInfo("Europe/Lisbon")

    def __init__(
        self,
        *,
        fetcher: Callable[..., Tuple[str, Mapping[str, str]]] = fetch_text,
        sleeper: Callable[[float], None] = time.sleep,
        request_interval: float = 0.25,
        max_pages: int = 200,
    ) -> None:
        self._fetcher = fetcher
        self._sleeper = sleeper
        self.request_interval = max(0.0, request_interval)
        self.max_pages = max_pages
        self.last_excluded_non_filings = 0

    def fetch(self, start_date: date, end_date: date) -> Iterable[Mapping[str, Any]]:
        if end_date < start_date:
            raise PublicDisclosureError("Euronext Lisbon date range is reversed")

        def url(page: int) -> str:
            return LISBON_ARCHIVE + "?" + urlencode({
                "field_company_pr_pub_datetime_start": f"{start_date.isoformat()} 00:00:00",
                "field_company_pr_pub_datetime_end": f"{end_date.isoformat()} 23:59:59",
                "page": page,
            })

        seen_ids: set[str] = set()
        output: list[Mapping[str, Any]] = []
        self.last_excluded_non_filings = 0
        for page in range(self.max_pages):
            if page and self.request_interval:
                self._sleeper(self.request_interval)
            retrieval_url = url(page)
            text, _ = self._fetcher(retrieval_url)
            # The legacy endpoint redirected to this page while silently
            # dropping all filters.  Require Drupal to echo both boundaries.
            if (
                f"{start_date.isoformat()} 00:00:00" not in text
                or f"{end_date.isoformat()} 23:59:59" not in text
            ):
                raise PublicDisclosureError(
                    "Euronext Lisbon did not retain the requested date filters"
                )
            records = list(_lisbon_records(text, retrieval_url))
            if not records:
                return output
            page_ids = {str(record["external_id"]) for record in records}
            if len(page_ids) != len(records) or page_ids & seen_ids:
                raise PublicDisclosureError(
                    "Euronext Lisbon pagination repeated a disclosure page"
                )
            seen_ids.update(page_ids)
            for record in records:
                if record.get("classification_code") != "official_filing":
                    self.last_excluded_non_filings += 1
                    continue
                output.append(record)
        raise PublicDisclosureError(
            f"Euronext Lisbon pagination reached max_pages={self.max_pages}"
        )


class NewswebNoConnector(PublicDisclosureConnector):
    name = "newsweb_no"
    provider = "NewsWeb (Oslo Børs)"
    source_wide_collection = True
    preserve_unmatched_records = True
    coverage_level = "official_newsweb"

    def __init__(self, client: Optional[Any] = None, universe: Optional[Mapping[str, Mapping[str, str]]] = None) -> None:
        super().__init__(client=client or NewswebClient(), universe=universe if universe is not None else no_universe_name_map(), normalizer=normalize_no_ticker, market=MARKET_NO)


class EuronextLisbonNewsConnector(PublicDisclosureConnector):
    name = "euronext_lisbon_news"
    provider = "Euronext Lisbon"
    source_wide_collection = True
    preserve_unmatched_records = True
    coverage_level = "official_exchange_archive"

    def __init__(self, client: Optional[Any] = None, universe: Optional[Mapping[str, Mapping[str, str]]] = None) -> None:
        super().__init__(client=client or EuronextLisbonClient(), universe=universe if universe is not None else pt_universe_name_map(), normalizer=normalize_pt_ticker, market=MARKET_PT)


__all__ = ["EuronextLisbonClient", "EuronextLisbonNewsConnector", "NewswebClient", "NewswebNoConnector"]
