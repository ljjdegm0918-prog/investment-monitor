"""Naver Finance news connector for market=kr companies."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, List, Mapping, Optional, Tuple

from ....models import CollectionRequest, InformationItem, MARKET_KR
from ..common import normalize_kr_ticker
from .client import NaverNewsClient, NaverNewsRequestError

LOGGER = logging.getLogger(__name__)

MAX_LOOKBACK_DAYS = 30


class NaverNewsConnector:
    """Collect Naver Finance stock news for active KR companies."""

    name = "naver_news"
    provider = "Naver Finance"
    max_lookback_days = MAX_LOOKBACK_DAYS

    def __init__(self, client: Optional[NaverNewsClient] = None) -> None:
        self._client = client or NaverNewsClient.from_environment()
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
            if market != MARKET_KR:
                LOGGER.info(
                    "naver_news ticker=%s market=%s skipped not_kr_market",
                    ticker,
                    market,
                )
                continue
            code = normalize_kr_ticker(ticker)
            try:
                records = self._client.fetch_news(
                    code,
                    request.start_date,
                    request.end_date,
                )
                items.extend(
                    _map_records(
                        records,
                        code=code,
                        collected_at=collected_at,
                    )
                )
            except Exception as error:
                message = str(error) or error.__class__.__name__
                failures.append((ticker, message))
                LOGGER.warning(
                    "naver_news ticker=%s status=failure error=%s",
                    ticker,
                    message,
                )
        self._last_errors = tuple(failures)
        if len(request.tickers) == 1 and failures:
            raise NaverNewsRequestError(failures[0][1])
        return items


def _map_records(
    records: List[Mapping[str, Any]],
    *,
    code: str,
    collected_at: datetime,
) -> List[InformationItem]:
    items: List[InformationItem] = []
    for record in records:
        office_id = str(record["office_id"])
        article_id = str(record["article_id"])
        items.append(
            InformationItem(
                source="naver_news",
                source_type="news",
                external_id=f"{office_id}:{article_id}",
                tickers=(code,),
                issuer=code,
                published_at=record["published"],
                title=str(record["title"]),
                document_type="news",
                url=(
                    "https://n.news.naver.com/mnews/article/"
                    f"{office_id}/{article_id}"
                ),
                collected_at=collected_at,
                raw_metadata={
                    "provider": "naver_finance",
                    "stock_code": code,
                    "office_id": office_id,
                    "article_id": article_id,
                    "source_name": str(record.get("provider") or ""),
                    "scraped": True,
                },
                market=MARKET_KR,
                summary=None,
                effective_at=record["published"],
            )
        )
    return items
