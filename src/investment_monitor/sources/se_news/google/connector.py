"""Google News (SE) connector for market=se companies."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Callable, List, Mapping, Optional, Tuple

from ....models import CollectionRequest, InformationItem, MARKET_SE
from ....web_repository import normalize_se_ticker
from ..symbols import se_yahoo_symbol
from .client import (
    GoogleSeNewsClient,
    GoogleSeNewsRequestError,
)

LOGGER = logging.getLogger(__name__)

MAX_LOOKBACK_DAYS = 30


class GoogleSeNewsConnector:
    """Collect Google News RSS items for market=se companies."""

    name = "google_news_se"
    provider = "Google News (SE)"
    max_lookback_days = MAX_LOOKBACK_DAYS

    def __init__(
        self,
        client: Optional[GoogleSeNewsClient] = None,
        symbol_for: Optional[Callable[[str], str]] = None,
    ) -> None:
        self._client = client or GoogleSeNewsClient.from_environment()
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
            if market != MARKET_SE:
                continue
            code = normalize_se_ticker(ticker)
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
                    "google_news_se ticker=%s status=failure error=%s",
                    ticker,
                    message,
                )
        self._last_errors = tuple(failures)
        if len(request.tickers) == 1 and failures:
            raise GoogleSeNewsRequestError(failures[0][1])
        return items


def _default_symbol_for(ticker: str) -> str:
    """Request-time symbol: canonical SE root plus the .ST suffix."""
    return se_yahoo_symbol(ticker)


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
                source="google_news_se",
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
                    "provider": "google_news_rss",
                    "stock_code": code,
                    "langs": "sv",
                    "scraped": True,
                },
                market=MARKET_SE,
                summary=record.get("summary"),
                effective_at=record["published"],
            )
        )
    return items
