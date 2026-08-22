# -*- coding: utf-8 -*-
"""BSE India corporate-announcements connector for ``market=in``."""

from __future__ import annotations

import logging
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, Iterable, List, Mapping, Optional, Tuple

from ...models import CollectionRequest, InformationItem, MARKET_IN
from ...provenance import build_raw_provenance
from ...web_repository import normalize_in_ticker
from .client import (
    BseIndiaAnnouncementsClient,
    BseIndiaAnnouncementsDataError,
    BseIndiaAnnouncementsRequestError,
    DEFAULT_ANNOUNCEMENTS_URL,
    REFERER,
)

LOGGER = logging.getLogger(__name__)
KOLKATA = timezone(timedelta(hours=5, minutes=30))
MAX_LOOKBACK_DAYS = 30


class BseIndiaAnnouncementsConnector:
    """Collect primary BSE India corporate announcements for Indian equities.

    The BSE feed is a second exchange source alongside NSE.  A caller may use
    a BSE symbol (``RELIANCE.BO``), the BSE six-digit scrip code, or an ISIN;
    the official active-equity directory resolves all three forms before the
    per-issuer announcement query is made.
    """

    name = "bse_india_announcements"
    provider = "BSE India"
    max_lookback_days = MAX_LOOKBACK_DAYS
    coverage_level = "official_second_venue"

    def __init__(
        self,
        client: Optional[BseIndiaAnnouncementsClient] = None,
    ) -> None:
        self._client = client or BseIndiaAnnouncementsClient.from_environment()
        self._last_errors: Tuple[Tuple[str, str], ...] = ()
        self.last_collection_status = "empty"

    @property
    def last_errors(self) -> Tuple[Tuple[str, str], ...]:
        return self._last_errors

    def collect(self, request: CollectionRequest) -> List[InformationItem]:
        targets = [
            ticker
            for ticker in request.tickers
            if request.market_for(ticker) == MARKET_IN
        ]
        if not targets:
            self._last_errors = ()
            self.last_collection_status = "empty"
            return []

        failures: List[Tuple[str, str]] = []
        collected_at = datetime.now(timezone.utc)
        try:
            security_index = _index_securities(self._client.fetch_securities())
        except Exception as error:  # noqa: BLE001 - normalize public source error
            message = str(error) or error.__class__.__name__
            failures.extend((ticker, message) for ticker in targets)
            self._last_errors = tuple(failures)
            self.last_collection_status = "failure"
            if len(targets) == 1:
                raise BseIndiaAnnouncementsRequestError(message) from error
            return []

        items: List[InformationItem] = []
        seen_scrips = set()
        for ticker in targets:
            security = _resolve_security(ticker, security_index)
            if security is None:
                # An NSE-listed company is not necessarily BSE-listed.  This
                # is an explicit, non-network miss rather than a fake success.
                failures.append((ticker, "BSE active-equity directory has no match."))
                continue
            scrip_code = str(security["SCRIP_CD"])
            if scrip_code in seen_scrips:
                continue
            seen_scrips.add(scrip_code)
            try:
                records = self._client.fetch_announcements(
                    scrip_code, request.start_date, request.end_date
                )
                items.extend(
                    _map_records(
                        records,
                        security=security,
                        requested_ticker=ticker,
                        client=self._client,
                        start_date=request.start_date,
                        end_date=request.end_date,
                        collected_at=collected_at,
                    )
                )
            except Exception as error:  # noqa: BLE001 - per issuer isolation
                message = str(error) or error.__class__.__name__
                failures.append((ticker, message))
                LOGGER.warning(
                    "bse_india_announcements ticker=%s status=failure error=%s",
                    ticker,
                    message,
                )
        self._last_errors = tuple(failures)
        if len(targets) == 1 and failures:
            self.last_collection_status = "failure"
            raise BseIndiaAnnouncementsRequestError(failures[0][1])
        result = _deduplicate_items(items)
        self.last_collection_status = (
            "partial" if failures and result else "failure" if failures else
            "success" if result else "empty"
        )
        return result


def _index_securities(
    securities: Iterable[Mapping[str, Any]],
) -> Mapping[str, Mapping[str, Any]]:
    index: Dict[str, Mapping[str, Any]] = {}
    for security in securities:
        code = str(security.get("SCRIP_CD") or "").strip()
        if not code:
            continue
        for key in (
            code,
            normalize_in_ticker(str(security.get("scrip_id") or "")),
            str(security.get("ISIN_NUMBER") or "").strip().upper(),
        ):
            if key:
                index.setdefault(key, security)
    return index


def _resolve_security(
    ticker: str,
    index: Mapping[str, Mapping[str, Any]],
) -> Optional[Mapping[str, Any]]:
    normalized = normalize_in_ticker(ticker)
    return index.get(normalized) or index.get(str(ticker).strip().upper())


def _map_records(
    records: Iterable[Mapping[str, Any]],
    *,
    security: Mapping[str, Any],
    requested_ticker: str,
    client: BseIndiaAnnouncementsClient,
    start_date: date,
    end_date: date,
    collected_at: datetime,
) -> List[InformationItem]:
    items: List[InformationItem] = []
    canonical_ticker = normalize_in_ticker(
        str(security.get("scrip_id") or requested_ticker)
    )
    for record in records:
        published = _parse_ist(record.get("DissemDT") or record.get("NEWS_DT"))
        if published is None:
            raise BseIndiaAnnouncementsDataError(
                "BSE announcement record has an invalid DissemDT/NEWS_DT."
            )
        local_date = published.astimezone(KOLKATA).date()
        if not start_date <= local_date <= end_date:
            continue
        news_id = str(record.get("NEWSID") or "").strip()
        if not news_id:
            raise BseIndiaAnnouncementsDataError("BSE announcement record lacks NEWSID.")
        headline = str(record.get("NEWSSUB") or record.get("HEADLINE") or "").strip()
        if not headline:
            raise BseIndiaAnnouncementsDataError("BSE announcement record lacks a headline.")
        attachment_name = str(record.get("ATTACHMENTNAME") or "").strip()
        attachment_url = client.attachment_url(attachment_name)
        official_url = attachment_url or REFERER
        items.append(
            InformationItem(
                source="bse_india_announcements",
                source_type="regulatory_filing",
                external_id=f"bse-india:{news_id}",
                tickers=(canonical_ticker,),
                issuer=str(
                    record.get("SLONGNAME")
                    or security.get("Issuer_Name")
                    or security.get("Scrip_Name")
                    or canonical_ticker
                ).strip(),
                published_at=published,
                title=headline,
                document_type=str(record.get("SUBCATNAME") or record.get("CATEGORYNAME") or "Corporate announcement"),
                url=official_url,
                collected_at=collected_at,
                raw_metadata={
                    **build_raw_provenance(
                        official_source_id=f"bse-india:{news_id}",
                        official_source_url=official_url,
                        retrieval_url=DEFAULT_ANNOUNCEMENTS_URL,
                        raw_payload=record,
                        raw_payload_format="json",
                        classification_code=str(record.get("SUBCATNAME") or record.get("CATEGORYNAME") or "") or None,
                        classification_label=str(record.get("SUBCATNAME") or record.get("CATEGORYNAME") or "Corporate announcement"),
                        published_at_raw=str(record.get("DissemDT") or record.get("NEWS_DT") or ""),
                        published_timezone="Asia/Kolkata",
                    ),
                    "provider": "bse_india_public_corporate_announcements",
                    "coverage_level": "official_second_venue",
                    "source_page": REFERER,
                    "news_id": news_id,
                    "bse_scrip_code": str(record.get("SCRIP_CD") or security.get("SCRIP_CD") or ""),
                    "bse_symbol": str(security.get("scrip_id") or ""),
                    "isin": str(security.get("ISIN_NUMBER") or ""),
                    "category": str(record.get("CATEGORYNAME") or ""),
                    "subcategory": str(record.get("SUBCATNAME") or ""),
                    "headline": str(record.get("HEADLINE") or ""),
                    "summary": str(record.get("MORE") or ""),
                    "attachment_name": attachment_name,
                    "attachment_size_bytes": record.get("Fld_Attachsize"),
                    "issuer_url": str(record.get("NSURL") or security.get("NSURL") or ""),
                    "disseminated_at_ist": str(record.get("DissemDT") or ""),
                },
                market=MARKET_IN,
                summary=str(record.get("MORE") or record.get("HEADLINE") or "") or None,
                effective_at=published,
            )
        )
    return items


def _parse_ist(value: Any) -> Optional[datetime]:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=KOLKATA)
    return parsed.astimezone(timezone.utc)


def _deduplicate_items(items: Iterable[InformationItem]) -> List[InformationItem]:
    by_id: Dict[str, InformationItem] = {}
    for item in items:
        by_id.setdefault(item.external_id, item)
    return list(by_id.values())
