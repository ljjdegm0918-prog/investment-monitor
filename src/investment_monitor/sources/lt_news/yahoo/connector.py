"""Yahoo Finance LT news connector for market=lt companies."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Mapping, Optional, Tuple

from ....models import CollectionRequest, InformationItem, MARKET_LT
from ....web_repository import normalize_lt_ticker
from ..symbols import lt_yahoo_symbol
from .client import (
    YahooLtNewsClient,
    YahooLtNewsRequestError,
)

LOGGER = logging.getLogger(__name__)

MAX_LOOKBACK_DAYS = 30


class YahooLtNewsConnector:
    """Collect Yahoo Finance Lithuania stock news for market=lt companies."""

    name = "yahoo_lt"
    provider = "Yahoo Finance LT"
    max_lookback_days = MAX_LOOKBACK_DAYS

    def __init__(
        self,
        client: Optional[YahooLtNewsClient] = None,
        symbol_for: Optional[Callable[[str], str]] = None,
    ) -> None:
        self._client = client or YahooLtNewsClient.from_environment()
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
            if market != MARKET_LT:
                LOGGER.info(
                    "yahoo_lt ticker=%s market=%s skipped not_lt_market",
                    ticker,
                    market,
                )
                continue
            code = normalize_lt_ticker(ticker)
            symbol = self._symbol_for(code)
            try:
                lt_records = self._client.fetch_news(
                    symbol,
                    request.start_date,
                    request.end_date,
                    lang="lt-LT",
                )
                en_records = self._client.fetch_news(
                    symbol,
                    request.start_date,
                    request.end_date,
                    lang="en-US",
                )
                items.extend(
                    _map_news(
                        lt_records,
                        en_records,
                        code=code,
                        collected_at=collected_at,
                    )
                )
            except Exception as error:
                message = str(error) or error.__class__.__name__
                failures.append((ticker, message))
                LOGGER.warning(
                    "yahoo_lt ticker=%s status=failure error=%s",
                    ticker,
                    message,
                )
        self._last_errors = tuple(failures)
        if len(request.tickers) == 1 and failures:
            raise YahooLtNewsRequestError(failures[0][1])
        return items


def _default_symbol_for(ticker: str) -> str:
    """Request-time symbol: canonical LT root plus the .VL suffix."""
    return lt_yahoo_symbol(ticker)


def _map_news(
    lt_records: List[Mapping[str, Any]],
    en_records: List[Mapping[str, Any]],
    *,
    code: str,
    collected_at: datetime,
) -> List[InformationItem]:
    merged: Dict[str, Dict[str, Optional[Mapping[str, Any]]]] = {}
    for record in lt_records:
        merged[str(record["external_id"])] = {"lt": record, "en": None}
    for record in en_records:
        key = str(record["external_id"])
        if key in merged:
            merged[key]["en"] = record
        else:
            merged[key] = {"lt": None, "en": record}

    items: List[InformationItem] = []
    for key, pair in merged.items():
        lt = pair["lt"]
        en = pair["en"]
        record = en or lt
        if record is None:
            continue
        lt_title = str(lt["title"]).strip() if lt else ""
        en_title = str(en["title"]).strip() if en else ""
        if en_title and lt_title and en_title != lt_title:
            title = en_title
            langs = "en+lt"
        else:
            title = lt_title or en_title
            langs = "lt" if lt else "en"
        raw_metadata: Dict[str, Any] = {
            "provider": "yahoo_finance_rss",
            "stock_code": code,
            "langs": langs,
            "scraped": True,
        }
        if langs == "en+lt":
            raw_metadata["title_en"] = en_title
            raw_metadata["title_lt"] = lt_title
        elif langs == "lt":
            raw_metadata["title_lt"] = lt_title
        else:
            raw_metadata["title_en"] = en_title
        items.append(
            InformationItem(
                source="yahoo_lt",
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
                market=MARKET_LT,
                summary=record.get("summary"),
                effective_at=record["published"],
            )
        )
    return items
