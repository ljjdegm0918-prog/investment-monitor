"""Yahoo Finance TW news connector for market=tw companies."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Mapping, Optional, Tuple

from ....models import CollectionRequest, InformationItem, MARKET_TW
from ....tw_universe import tw_universe_name_map
from ...twse_material.client import normalize_tw_ticker
from .client import (
    YahooTwNewsClient,
    YahooTwNewsRequestError,
)

LOGGER = logging.getLogger(__name__)

MAX_LOOKBACK_DAYS = 30


class YahooTwNewsConnector:
    """Collect Yahoo Finance Taiwan stock news for market=tw companies."""

    name = "yahoo_tw"
    provider = "Yahoo Finance TW"
    max_lookback_days = MAX_LOOKBACK_DAYS

    def __init__(
        self,
        client: Optional[YahooTwNewsClient] = None,
        symbol_for: Optional[Callable[[str], str]] = None,
    ) -> None:
        self._client = client or YahooTwNewsClient.from_environment()
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
            if market != MARKET_TW:
                continue
            code = normalize_tw_ticker(ticker)
            symbol = self._symbol_for(code)
            try:
                zh_records = self._client.fetch_news(
                    symbol,
                    request.start_date,
                    request.end_date,
                    lang="zh-TW",
                )
                en_records = self._client.fetch_news(
                    symbol,
                    request.start_date,
                    request.end_date,
                    lang="en-US",
                )
                items.extend(
                    _map_news(
                        zh_records,
                        en_records,
                        code=code,
                        collected_at=collected_at,
                    )
                )
            except Exception as error:
                message = str(error) or error.__class__.__name__
                failures.append((ticker, message))
                LOGGER.warning(
                    "yahoo_tw ticker=%s status=failure error=%s",
                    ticker,
                    message,
                )
        self._last_errors = tuple(failures)
        if len(request.tickers) == 1 and failures:
            raise YahooTwNewsRequestError(failures[0][1])
        return items


def _default_symbol_for(ticker: str) -> str:
    """Request-time symbol: TPEx/ESB -> .TWO, otherwise .TW."""
    exchange = str(
        (tw_universe_name_map().get(ticker) or {}).get("exchange") or ""
    )
    return f"{ticker}.TWO" if exchange in {"TPEx", "ESB"} else f"{ticker}.TW"


def _map_news(
    zh_records: List[Mapping[str, Any]],
    en_records: List[Mapping[str, Any]],
    *,
    code: str,
    collected_at: datetime,
) -> List[InformationItem]:
    merged: Dict[str, Dict[str, Optional[Mapping[str, Any]]]] = {}
    for record in zh_records:
        merged[str(record["external_id"])] = {"zh": record, "en": None}
    for record in en_records:
        key = str(record["external_id"])
        if key in merged:
            merged[key]["en"] = record
        else:
            merged[key] = {"zh": None, "en": record}

    items: List[InformationItem] = []
    for key, pair in merged.items():
        zh = pair["zh"]
        en = pair["en"]
        record = en or zh
        if record is None:
            continue
        zh_title = str(zh["title"]).strip() if zh else ""
        en_title = str(en["title"]).strip() if en else ""
        if en_title and zh_title and en_title != zh_title:
            title = en_title
            langs = "en+zh"
        else:
            title = zh_title or en_title
            langs = "zh" if zh else "en"
        raw_metadata: Dict[str, Any] = {
            "provider": "yahoo_finance_rss",
            "stock_code": code,
            "langs": langs,
            "scraped": True,
        }
        if langs == "en+zh":
            raw_metadata["title_en"] = en_title
            raw_metadata["title_zh"] = zh_title
        elif langs == "zh":
            raw_metadata["title_zh"] = zh_title
        else:
            raw_metadata["title_en"] = en_title
        items.append(
            InformationItem(
                source="yahoo_tw",
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
                market=MARKET_TW,
                summary=record.get("summary"),
                effective_at=record["published"],
            )
        )
    return items
