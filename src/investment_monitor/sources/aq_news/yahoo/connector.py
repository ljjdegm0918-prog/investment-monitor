"""Yahoo Finance AQ news connector for market=aq companies."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Mapping, Optional, Tuple

from ....models import CollectionRequest, InformationItem, MARKET_AQ
from ....web_repository import normalize_aq_ticker
from ..symbols import aq_yahoo_symbol
from .client import (
    YahooAqNewsClient,
    YahooAqNewsRequestError,
)

LOGGER = logging.getLogger(__name__)

MAX_LOOKBACK_DAYS = 30


class YahooAqNewsConnector:
    """Collect Yahoo Finance Aquis stock news for market=aq companies."""

    name = "yahoo_aq"
    provider = "Yahoo Finance AQ"
    max_lookback_days = MAX_LOOKBACK_DAYS

    def __init__(
        self,
        client: Optional[YahooAqNewsClient] = None,
        symbol_for: Optional[Callable[[str], str]] = None,
    ) -> None:
        self._client = client or YahooAqNewsClient.from_environment()
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
            if market != MARKET_AQ:
                LOGGER.info(
                    "yahoo_aq ticker=%s market=%s skipped not_aq_market",
                    ticker,
                    market,
                )
                continue
            code = normalize_aq_ticker(ticker)
            symbol = self._symbol_for(code)
            try:
                gb_records = self._client.fetch_news(
                    symbol,
                    request.start_date,
                    request.end_date,
                    lang="en-GB",
                )
                us_records = self._client.fetch_news(
                    symbol,
                    request.start_date,
                    request.end_date,
                    lang="en-US",
                )
                items.extend(
                    _map_news(
                        gb_records,
                        us_records,
                        code=code,
                        collected_at=collected_at,
                    )
                )
            except Exception as error:
                message = str(error) or error.__class__.__name__
                failures.append((ticker, message))
                LOGGER.warning(
                    "yahoo_aq ticker=%s status=failure error=%s",
                    ticker,
                    message,
                )
        self._last_errors = tuple(failures)
        if len(request.tickers) == 1 and failures:
            raise YahooAqNewsRequestError(failures[0][1])
        return items


def _default_symbol_for(ticker: str) -> str:
    """Request-time symbol: canonical AQ root plus the .AQ suffix."""
    return aq_yahoo_symbol(ticker)


def _map_news(
    gb_records: List[Mapping[str, Any]],
    us_records: List[Mapping[str, Any]],
    *,
    code: str,
    collected_at: datetime,
) -> List[InformationItem]:
    merged: Dict[str, Dict[str, Optional[Mapping[str, Any]]]] = {}
    for record in gb_records:
        merged[str(record["external_id"])] = {"gb": record, "us": None}
    for record in us_records:
        key = str(record["external_id"])
        if key in merged:
            merged[key]["us"] = record
        else:
            merged[key] = {"gb": None, "us": record}

    items: List[InformationItem] = []
    for key, pair in merged.items():
        gb = pair["gb"]
        us = pair["us"]
        record = us or gb
        if record is None:
            continue
        gb_title = str(gb["title"]).strip() if gb else ""
        us_title = str(us["title"]).strip() if us else ""
        if us_title and gb_title and us_title != gb_title:
            title = us_title
            langs = "en+gb"
        else:
            title = gb_title or us_title
            langs = "en-GB" if gb else "en-US"
        raw_metadata: Dict[str, Any] = {
            "provider": "yahoo_finance_rss",
            "stock_code": code,
            "langs": langs,
            "scraped": True,
        }
        if langs == "en+gb":
            raw_metadata["title_en"] = us_title
            raw_metadata["title_gb"] = gb_title
        elif langs == "en-GB":
            raw_metadata["title_gb"] = gb_title
        else:
            raw_metadata["title_en"] = us_title
        items.append(
            InformationItem(
                source="yahoo_aq",
                source_type="news",
                external_id=key,
                tickers=(code,),
                issuer=code,
                published_at=record["published"],
                title=title,
                document_type="news",
                url=str(record["url"]),
                collected_at=collected_at,
                raw_metadata=raw_metadata,
                market=MARKET_AQ,
                summary=record.get("summary"),
                effective_at=record["published"],
            )
        )
    return items
