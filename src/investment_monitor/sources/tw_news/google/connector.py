"""Google News (TW) connector for market=tw companies."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, List, Mapping, Optional, Tuple

from ....models import CollectionRequest, InformationItem, MARKET_TW
from ...twse_material.client import normalize_tw_ticker
from .client import (
    GoogleTwNewsClient,
    GoogleTwNewsRequestError,
)

LOGGER = logging.getLogger(__name__)

MAX_LOOKBACK_DAYS = 30


class GoogleTwNewsConnector:
    """Collect Google News RSS items for market=tw companies."""

    name = "google_news_tw"
    provider = "Google News (TW)"
    max_lookback_days = MAX_LOOKBACK_DAYS

    def __init__(self, client: Optional[GoogleTwNewsClient] = None) -> None:
        self._client = client or GoogleTwNewsClient.from_environment()
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
            if market != MARKET_TW:
                continue
            code = normalize_tw_ticker(ticker)
            try:
                records = self._client.fetch_news(
                    f"{code}.TW",
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
                    "google_news_tw ticker=%s status=failure error=%s",
                    ticker,
                    message,
                )
        self._last_errors = tuple(failures)
        if len(request.tickers) == 1 and failures:
            raise GoogleTwNewsRequestError(failures[0][1])
        return items


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
                source="google_news_tw",
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
                    "langs": "zh",
                    "scraped": True,
                },
                market=MARKET_TW,
                summary=record.get("summary"),
                effective_at=record["published"],
            )
        )
    return items
