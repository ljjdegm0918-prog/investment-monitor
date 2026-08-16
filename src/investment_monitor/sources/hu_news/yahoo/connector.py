"""Yahoo Finance HU news connector for market=hu companies."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Mapping, Optional, Tuple

from ....models import CollectionRequest, InformationItem, MARKET_HU
from ....web_repository import normalize_hu_ticker
from ..symbols import hu_yahoo_symbol
from .client import (
    YahooHuNewsClient,
    YahooHuNewsRequestError,
)

LOGGER = logging.getLogger(__name__)

MAX_LOOKBACK_DAYS = 30


class YahooHuNewsConnector:
    """Collect Yahoo Finance Hungary stock news for market=hu companies."""

    name = "yahoo_hu"
    provider = "Yahoo Finance HU"
    max_lookback_days = MAX_LOOKBACK_DAYS

    def __init__(
        self,
        client: Optional[YahooHuNewsClient] = None,
        symbol_for: Optional[Callable[[str], str]] = None,
    ) -> None:
        self._client = client or YahooHuNewsClient.from_environment()
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
            if market != MARKET_HU:
                LOGGER.info(
                    "yahoo_hu ticker=%s market=%s skipped not_hu_market",
                    ticker,
                    market,
                )
                continue
            code = normalize_hu_ticker(ticker)
            symbol = self._symbol_for(code)
            try:
                hu_records = self._client.fetch_news(
                    symbol,
                    request.start_date,
                    request.end_date,
                    lang="hu-HU",
                )
                en_records = self._client.fetch_news(
                    symbol,
                    request.start_date,
                    request.end_date,
                    lang="en-US",
                )
                items.extend(
                    _map_news(
                        hu_records,
                        en_records,
                        code=code,
                        collected_at=collected_at,
                    )
                )
            except Exception as error:
                message = str(error) or error.__class__.__name__
                failures.append((ticker, message))
                LOGGER.warning(
                    "yahoo_hu ticker=%s status=failure error=%s",
                    ticker,
                    message,
                )
        self._last_errors = tuple(failures)
        if len(request.tickers) == 1 and failures:
            raise YahooHuNewsRequestError(failures[0][1])
        return items


def _default_symbol_for(ticker: str) -> str:
    """Request-time symbol: canonical HU root plus the .BU suffix."""
    return hu_yahoo_symbol(ticker)


def _map_news(
    hu_records: List[Mapping[str, Any]],
    en_records: List[Mapping[str, Any]],
    *,
    code: str,
    collected_at: datetime,
) -> List[InformationItem]:
    merged: Dict[str, Dict[str, Optional[Mapping[str, Any]]]] = {}
    for record in hu_records:
        merged[str(record["external_id"])] = {"hu": record, "en": None}
    for record in en_records:
        key = str(record["external_id"])
        if key in merged:
            merged[key]["en"] = record
        else:
            merged[key] = {"hu": None, "en": record}

    items: List[InformationItem] = []
    for key, pair in merged.items():
        hu = pair["hu"]
        en = pair["en"]
        record = en or hu
        if record is None:
            continue
        hu_title = str(hu["title"]).strip() if hu else ""
        en_title = str(en["title"]).strip() if en else ""
        if en_title and hu_title and en_title != hu_title:
            title = en_title
            langs = "en+hu"
        else:
            title = hu_title or en_title
            langs = "hu" if hu else "en"
        raw_metadata: Dict[str, Any] = {
            "provider": "yahoo_finance_rss",
            "stock_code": code,
            "langs": langs,
            "scraped": True,
        }
        if langs == "en+hu":
            raw_metadata["title_en"] = en_title
            raw_metadata["title_hu"] = hu_title
        elif langs == "hu":
            raw_metadata["title_hu"] = hu_title
        else:
            raw_metadata["title_en"] = en_title
        items.append(
            InformationItem(
                source="yahoo_hu",
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
                market=MARKET_HU,
                summary=record.get("summary"),
                effective_at=record["published"],
            )
        )
    return items
