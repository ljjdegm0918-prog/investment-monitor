"""Yahoo Finance IN news connector for market=in companies."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Mapping, Optional, Tuple

from ....models import CollectionRequest, InformationItem, MARKET_IN
from ....web_repository import normalize_in_ticker
from ..symbols import in_yahoo_symbol
from .client import (
    YahooInNewsClient,
    YahooInNewsRequestError,
)

LOGGER = logging.getLogger(__name__)

MAX_LOOKBACK_DAYS = 30


class YahooInNewsConnector:
    """Collect Yahoo Finance India stock news for market=in companies."""

    name = "yahoo_in"
    provider = "Yahoo Finance IN"
    max_lookback_days = MAX_LOOKBACK_DAYS

    def __init__(
        self,
        client: Optional[YahooInNewsClient] = None,
        symbol_for: Optional[Callable[[str], str]] = None,
    ) -> None:
        self._client = client or YahooInNewsClient.from_environment()
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
            if market != MARKET_IN:
                LOGGER.info(
                    "yahoo_in ticker=%s market=%s skipped not_in_market",
                    ticker,
                    market,
                )
                continue
            code = normalize_in_ticker(ticker)
            symbol = self._symbol_for(code)
            try:
                in_records = self._client.fetch_news(
                    symbol,
                    request.start_date,
                    request.end_date,
                    lang="en-IN",
                )
                en_records = self._client.fetch_news(
                    symbol,
                    request.start_date,
                    request.end_date,
                    lang="en-US",
                )
                items.extend(
                    _map_news(
                        in_records,
                        en_records,
                        code=code,
                        collected_at=collected_at,
                    )
                )
            except Exception as error:
                message = str(error) or error.__class__.__name__
                failures.append((ticker, message))
                LOGGER.warning(
                    "yahoo_in ticker=%s status=failure error=%s",
                    ticker,
                    message,
                )
        self._last_errors = tuple(failures)
        if len(request.tickers) == 1 and failures:
            raise YahooInNewsRequestError(failures[0][1])
        return items


def _default_symbol_for(ticker: str) -> str:
    """Request-time symbol: canonical IN root plus the .NS suffix."""
    return in_yahoo_symbol(ticker)


def _map_news(
    in_records: List[Mapping[str, Any]],
    en_records: List[Mapping[str, Any]],
    *,
    code: str,
    collected_at: datetime,
) -> List[InformationItem]:
    merged: Dict[str, Dict[str, Optional[Mapping[str, Any]]]] = {}
    for record in in_records:
        merged[str(record["external_id"])] = {"in": record, "en": None}
    for record in en_records:
        key = str(record["external_id"])
        if key in merged:
            merged[key]["en"] = record
        else:
            merged[key] = {"in": None, "en": record}

    items: List[InformationItem] = []
    for key, pair in merged.items():
        in_record = pair["in"]
        en = pair["en"]
        record = en or in_record
        if record is None:
            continue
        in_title = str(in_record["title"]).strip() if in_record else ""
        en_title = str(en["title"]).strip() if en else ""
        if en_title and in_title and en_title != in_title:
            title = en_title
            langs = "en+in"
        else:
            title = in_title or en_title
            langs = "in" if in_record else "en"
        raw_metadata: Dict[str, Any] = {
            "provider": "yahoo_finance_rss",
            "stock_code": code,
            "langs": langs,
            "scraped": True,
        }
        if langs == "en+in":
            raw_metadata["title_en"] = en_title
            raw_metadata["title_in"] = in_title
        elif langs == "in":
            raw_metadata["title_in"] = in_title
        else:
            raw_metadata["title_en"] = en_title
        items.append(
            InformationItem(
                source="yahoo_in",
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
                market=MARKET_IN,
                summary=record.get("summary"),
                effective_at=record["published"],
            )
        )
    return items
