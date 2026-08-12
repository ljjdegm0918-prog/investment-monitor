"""Yahoo Finance JP news connector for market=jp companies."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Callable, List, Mapping, Optional, Tuple

from ....models import CollectionRequest, InformationItem, MARKET_JP
from ..symbols import jp_yahoo_symbol, normalize_jp_ticker
from .client import (
    YahooJpNewsClient,
    YahooJpNewsRequestError,
)

LOGGER = logging.getLogger(__name__)

MAX_LOOKBACK_DAYS = 30


class YahooJpNewsConnector:
    """Collect Yahoo Finance JP stock news for market=jp companies."""

    name = "yahoo_jp"
    provider = "Yahoo Finance JP"
    max_lookback_days = MAX_LOOKBACK_DAYS

    def __init__(
        self,
        client: Optional[YahooJpNewsClient] = None,
        symbol_for: Optional[Callable[[str], str]] = None,
    ) -> None:
        self._client = client or YahooJpNewsClient.from_environment()
        self._symbol_for = symbol_for or _default_symbol_for
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
            if market != MARKET_JP:
                LOGGER.info(
                    "yahoo_jp ticker=%s market=%s skipped not_jp_market",
                    ticker,
                    market,
                )
                continue
            code = normalize_jp_ticker(ticker)
            symbol = self._symbol_for(code)
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
                    "yahoo_jp ticker=%s status=failure error=%s",
                    ticker,
                    message,
                )
        self._last_errors = tuple(failures)
        if len(request.tickers) == 1 and failures:
            raise YahooJpNewsRequestError(failures[0][1])
        return items


def _default_symbol_for(ticker: str) -> str:
    return jp_yahoo_symbol(ticker)


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
                source="yahoo_jp",
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
                market=MARKET_JP,
                summary=record.get("summary"),
                effective_at=record["published"],
            )
        )
    return items
