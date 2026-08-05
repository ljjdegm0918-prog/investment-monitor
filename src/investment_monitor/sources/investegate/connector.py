"""Investegate RNS-class connector for market=uk companies."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, List, Mapping, Optional, Tuple

from ...models import CollectionRequest, InformationItem, MARKET_UK
from .client import (
    InvestegateClient,
    InvestegateRequestError,
    stable_fallback_id,
)

LOGGER = logging.getLogger(__name__)

MAX_LOOKBACK_DAYS = 30


class InvestegateConnector:
    """Collect Investegate RNS-class announcements for active UK companies."""

    name = "investegate"
    provider = "Investegate"
    max_lookback_days = MAX_LOOKBACK_DAYS

    def __init__(self, client: Optional[InvestegateClient] = None) -> None:
        self._client = client or InvestegateClient.from_environment()
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
            if market != MARKET_UK:
                LOGGER.info(
                    "investegate ticker=%s market=%s skipped not_uk_market",
                    ticker,
                    market,
                )
                continue
            code = ticker.strip().upper()
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
                    "investegate ticker=%s status=failure error=%s",
                    ticker,
                    message,
                )
        self._last_errors = tuple(failures)
        if len(request.tickers) == 1 and failures:
            raise InvestegateRequestError(failures[0][1])
        return items


def _map_announcements(
    records: List[Mapping[str, Any]],
    *,
    code: str,
    collected_at: datetime,
) -> List[InformationItem]:
    items: List[InformationItem] = []
    for record in records:
        rns_id = str(record["rns_id"])
        items.append(
            InformationItem(
                source="investegate",
                source_type="regulatory_filing",
                external_id=rns_id or stable_fallback_id(str(record["url"])),
                tickers=(code,),
                issuer=code,
                published_at=record["published"],
                title=str(record["title"]),
                document_type="rns_announcement",
                url=str(record["url"]),
                collected_at=collected_at,
                raw_metadata={
                    "provider": "investegate",
                    "stock_code": code,
                    "rns_id": rns_id,
                    "source_label": "RNS",
                    "scraped": True,
                },
                market=MARKET_UK,
                summary=None,
                effective_at=record["published"],
            )
        )
    return items
