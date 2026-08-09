"""ASX company announcements connector for market=au companies."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import List, Mapping, Optional, Tuple

from ...models import CollectionRequest, InformationItem, MARKET_AU
from ...web_repository import normalize_au_ticker
from .client import (
    AsxAnnouncementsClient,
    AsxAnnouncementsRequestError,
)

LOGGER = logging.getLogger(__name__)

MAX_LOOKBACK_DAYS = 30


class AsxAnnouncementsConnector:
    """Collect ASX company announcements for market=au companies."""

    name = "asx_announcements"
    provider = "ASX Market Announcements"
    max_lookback_days = MAX_LOOKBACK_DAYS

    def __init__(
        self,
        client: Optional[AsxAnnouncementsClient] = None,
    ) -> None:
        self._client = client or AsxAnnouncementsClient.from_environment()
        self._last_errors: Tuple[Tuple[str, str], ...] = ()

    @property
    def last_errors(self) -> Tuple[Tuple[str, str], ...]:
        return self._last_errors

    def collect(self, request: CollectionRequest) -> List[InformationItem]:
        items: List[InformationItem] = []
        failures: List[Tuple[str, str]] = []
        collected_at = datetime.now(timezone.utc)
        for ticker in request.tickers:
            market = request.market_for(ticker)
            if market != MARKET_AU:
                LOGGER.info(
                    "asx_announcements ticker=%s market=%s skipped not_au",
                    ticker,
                    market,
                )
                continue
            code = normalize_au_ticker(ticker)
            try:
                records = self._client.fetch_announcements(
                    code,
                    request.start_date,
                    request.end_date,
                )
                items.extend(
                    _map_announcements(
                        records,
                        code=code,
                        collected_at=collected_at,
                    )
                )
            except Exception as error:
                message = str(error) or error.__class__.__name__
                failures.append((ticker, message))
                LOGGER.warning(
                    "asx_announcements ticker=%s status=failure error=%s",
                    ticker,
                    message,
                )
        self._last_errors = tuple(failures)
        if len(request.tickers) == 1 and failures:
            raise AsxAnnouncementsRequestError(failures[0][1])
        return items


def _map_announcements(
    records: List[Mapping[str, Any]],
    *,
    code: str,
    collected_at: datetime,
) -> List[InformationItem]:
    items: List[InformationItem] = []
    for record in records:
        items.append(
            InformationItem(
                source="asx_announcements",
                source_type="regulatory_filing",
                external_id=str(record["external_id"]),
                tickers=(code,),
                issuer=code,
                published_at=record["published"],
                title=str(record["title"]),
                document_type=str(
                    record.get("announcement_type") or "announcement"
                ),
                url=str(record["url"]),
                collected_at=collected_at,
                raw_metadata={
                    "provider": "asx_markitdigital_research_api",
                    "stock_code": code,
                    "document_key": str(record["external_id"]),
                    "announcement_type": str(
                        record.get("announcement_type") or ""
                    ),
                    "file_size": str(record.get("file_size") or ""),
                    "is_price_sensitive": bool(
                        record.get("is_price_sensitive")
                    ),
                    "api_url": str(record["url"]),
                },
                market=MARKET_AU,
                summary=None,
                effective_at=record["published"],
            )
        )
    return items
