"""Yahoo Finance KR news connector for market=kr companies."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Mapping, Optional, Tuple

from ....models import CollectionRequest, InformationItem, MARKET_KR
from ..common import normalize_kr_ticker
from ..symbols import kr_yahoo_symbol
from .client import (
    YahooKrNewsClient,
    YahooKrNewsRequestError,
)

LOGGER = logging.getLogger(__name__)

MAX_LOOKBACK_DAYS = 30


class YahooKrNewsConnector:
    """Collect Yahoo Finance KR stock news for market=kr companies."""

    name = "yahoo_kr"
    provider = "Yahoo Finance KR"
    max_lookback_days = MAX_LOOKBACK_DAYS

    def __init__(
        self,
        client: Optional[YahooKrNewsClient] = None,
        symbol_for: Optional[Callable[[str], str]] = None,
    ) -> None:
        self._client = client or YahooKrNewsClient.from_environment()
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
            if market != MARKET_KR:
                LOGGER.info(
                    "yahoo_kr ticker=%s market=%s skipped not_kr_market",
                    ticker,
                    market,
                )
                continue
            code = normalize_kr_ticker(ticker)
            symbol = self._symbol_for(code)
            try:
                ko_records = self._client.fetch_news(
                    symbol,
                    request.start_date,
                    request.end_date,
                    lang="ko-KR",
                )
                en_records = self._client.fetch_news(
                    symbol,
                    request.start_date,
                    request.end_date,
                    lang="en-US",
                )
                items.extend(
                    _map_news(
                        ko_records,
                        en_records,
                        code=code,
                        collected_at=collected_at,
                    )
                )
            except Exception as error:
                message = str(error) or error.__class__.__name__
                failures.append((ticker, message))
                LOGGER.warning(
                    "yahoo_kr ticker=%s status=failure error=%s",
                    ticker,
                    message,
                )
        self._last_errors = tuple(failures)
        if len(request.tickers) == 1 and failures:
            raise YahooKrNewsRequestError(failures[0][1])
        return items


def _default_symbol_for(ticker: str) -> str:
    return kr_yahoo_symbol(ticker)


def _map_news(
    ko_records: List[Mapping[str, Any]],
    en_records: List[Mapping[str, Any]],
    *,
    code: str,
    collected_at: datetime,
) -> List[InformationItem]:
    merged: Dict[str, Dict[str, Optional[Mapping[str, Any]]]] = {}
    for record in ko_records:
        merged[str(record["external_id"])] = {"ko": record, "en": None}
    for record in en_records:
        key = str(record["external_id"])
        if key in merged:
            merged[key]["en"] = record
        else:
            merged[key] = {"ko": None, "en": record}

    items: List[InformationItem] = []
    for key, pair in merged.items():
        ko = pair["ko"]
        en = pair["en"]
        record = en or ko
        if record is None:
            continue
        ko_title = str(ko["title"]).strip() if ko else ""
        en_title = str(en["title"]).strip() if en else ""
        if en_title and ko_title and en_title != ko_title:
            title = en_title
            langs = "en+ko"
        else:
            title = ko_title or en_title
            langs = "ko" if ko else "en"
        raw_metadata: Dict[str, Any] = {
            "provider": "yahoo_finance_rss",
            "stock_code": code,
            "langs": langs,
            "scraped": True,
        }
        if langs == "en+ko":
            raw_metadata["title_en"] = en_title
            raw_metadata["title_ko"] = ko_title
        elif langs == "ko":
            raw_metadata["title_ko"] = ko_title
        else:
            raw_metadata["title_en"] = en_title
        items.append(
            InformationItem(
                source="yahoo_kr",
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
                market=MARKET_KR,
                summary=record.get("summary"),
                effective_at=record["published"],
            )
        )
    return items
