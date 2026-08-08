"""Yahoo Finance AU news connector for market=au companies."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Callable, List, Mapping, Optional, Tuple

from ....models import CollectionRequest, InformationItem, MARKET_AU
from ....web_repository import normalize_au_ticker
from ..symbols import au_yahoo_symbol
from .client import (
    YahooAuNewsClient,
    YahooAuNewsRequestError,
)

LOGGER = logging.getLogger(__name__)

MAX_LOOKBACK_DAYS = 30


class YahooAuNewsConnector:
    """Collect Yahoo Finance AU stock news for active AU companies."""

    name = "yahoo_au"
    provider = "Yahoo Finance AU"
    max_lookback_days = MAX_LOOKBACK_DAYS

    def __init__(
        self,
        client: Optional[YahooAuNewsClient] = None,
        symbol_for: Optional[Callable[[str], str]] = None,
    ) -> None:
        self._client = client or YahooAuNewsClient.from_environment()
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
            if market != MARKET_AU:
                LOGGER.info(
                    "yahoo_au ticker=%s market=%s skipped not_au_market",
                    ticker,
                    market,
                )
                continue
            code = normalize_au_ticker(ticker)
            symbol = self._symbol_for(code)
            try:
                records = self._client.fetch_news(
                    symbol,
                    request.start_date,
                    request.end_date,
                    lang="en-AU",
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
                    "yahoo_au ticker=%s status=failure error=%s",
                    ticker,
                    message,
                )
        self._last_errors = tuple(failures)
        if len(request.tickers) == 1 and failures:
            raise YahooAuNewsRequestError(failures[0][1])
        return items


def _default_symbol_for(ticker: str) -> str:
    """Request-time symbol: canonical AU root plus the .AX suffix."""
    return au_yahoo_symbol(ticker)


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
                source="yahoo_au",
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
                    "langs": "en",
                    "scraped": True,
                },
                market=MARKET_AU,
                summary=record.get("summary"),
                effective_at=record["published"],
            )
        )
    return items
