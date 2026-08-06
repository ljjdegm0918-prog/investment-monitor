"""Yahoo Finance UK news connector for market=uk companies."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, List, Mapping, Optional, Tuple

from ....models import CollectionRequest, InformationItem, MARKET_UK
from .client import (
    YahooNewsClient,
    YahooNewsRequestError,
)

LOGGER = logging.getLogger(__name__)

MAX_LOOKBACK_DAYS = 30


class YahooNewsConnector:
    """Collect Yahoo Finance UK stock news for active UK companies."""

    name = "yahoo_uk"
    provider = "Yahoo Finance UK"
    max_lookback_days = MAX_LOOKBACK_DAYS

    def __init__(self, client: Optional[YahooNewsClient] = None) -> None:
        self._client = client or YahooNewsClient.from_environment()
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
                    "yahoo_uk ticker=%s market=%s skipped not_uk_market",
                    ticker,
                    market,
                )
                continue
            code = ticker.strip().upper()
            symbol = _yahoo_symbol(code)
            try:
                records = self._client.fetch_news(
                    symbol,
                    request.start_date,
                    request.end_date,
                )
                items.extend(
                    _map_news(
                        records,
                        code=code,
                        collected_at=collected_at,
                    )
                )
            except Exception as error:
                message = str(error) or error.__class__.__name__
                failures.append((ticker, message))
                LOGGER.warning(
                    "yahoo_uk ticker=%s status=failure error=%s",
                    ticker,
                    message,
                )
        self._last_errors = tuple(failures)
        if len(request.tickers) == 1 and failures:
            raise YahooNewsRequestError(failures[0][1])
        return items


def _yahoo_symbol(code: str) -> str:
    """Convert a UK ticker to a Yahoo symbol at request time only."""
    if code.endswith(".L"):
        return code
    return code.rstrip(".") + ".L"


def _map_news(
    records: List[Mapping[str, Any]],
    *,
    code: str,
    collected_at: datetime,
) -> List[InformationItem]:
    items: List[InformationItem] = []
    for record in records:
        items.append(
            InformationItem(
                source="yahoo_uk",
                source_type="news",
                external_id=str(record["external_id"]),
                tickers=(code,),
                issuer=code,
                published_at=record["published"],
                title=str(record["title"]),
                document_type="news",
                url=str(record["url"]),
                collected_at=collected_at,
                raw_metadata={
                    "provider": "yahoo_finance_rss",
                    "stock_code": code,
                    "scraped": True,
                },
                market=MARKET_UK,
                summary=record.get("summary"),
                effective_at=record["published"],
            )
        )
    return items
