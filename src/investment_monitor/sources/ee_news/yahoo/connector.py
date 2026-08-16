"""Yahoo Finance EE news connector for market=ee companies."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Mapping, Optional, Tuple

from ....models import CollectionRequest, InformationItem, MARKET_EE
from ....web_repository import normalize_ee_ticker
from ..symbols import ee_yahoo_symbol
from .client import (
    YahooEeNewsClient,
    YahooEeNewsRequestError,
)

LOGGER = logging.getLogger(__name__)

MAX_LOOKBACK_DAYS = 30


class YahooEeNewsConnector:
    """Collect Yahoo Finance Estonia stock news for market=ee companies."""

    name = "yahoo_ee"
    provider = "Yahoo Finance EE"
    max_lookback_days = MAX_LOOKBACK_DAYS

    def __init__(
        self,
        client: Optional[YahooEeNewsClient] = None,
        symbol_for: Optional[Callable[[str], str]] = None,
    ) -> None:
        self._client = client or YahooEeNewsClient.from_environment()
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
            if market != MARKET_EE:
                LOGGER.info(
                    "yahoo_ee ticker=%s market=%s skipped not_ee_market",
                    ticker,
                    market,
                )
                continue
            code = normalize_ee_ticker(ticker)
            symbol = self._symbol_for(code)
            try:
                ee_records = self._client.fetch_news(
                    symbol,
                    request.start_date,
                    request.end_date,
                    lang="et-EE",
                )
                en_records = self._client.fetch_news(
                    symbol,
                    request.start_date,
                    request.end_date,
                    lang="en-US",
                )
                items.extend(
                    _map_news(
                        ee_records,
                        en_records,
                        code=code,
                        collected_at=collected_at,
                    )
                )
            except Exception as error:
                message = str(error) or error.__class__.__name__
                failures.append((ticker, message))
                LOGGER.warning(
                    "yahoo_ee ticker=%s status=failure error=%s",
                    ticker,
                    message,
                )
        self._last_errors = tuple(failures)
        if len(request.tickers) == 1 and failures:
            raise YahooEeNewsRequestError(failures[0][1])
        return items


def _default_symbol_for(ticker: str) -> str:
    """Request-time symbol: canonical EE root plus the .TL suffix."""
    return ee_yahoo_symbol(ticker)


def _map_news(
    ee_records: List[Mapping[str, Any]],
    en_records: List[Mapping[str, Any]],
    *,
    code: str,
    collected_at: datetime,
) -> List[InformationItem]:
    merged: Dict[str, Dict[str, Optional[Mapping[str, Any]]]] = {}
    for record in ee_records:
        merged[str(record["external_id"])] = {"ee": record, "en": None}
    for record in en_records:
        key = str(record["external_id"])
        if key in merged:
            merged[key]["en"] = record
        else:
            merged[key] = {"ee": None, "en": record}

    items: List[InformationItem] = []
    for key, pair in merged.items():
        ee = pair["ee"]
        en = pair["en"]
        record = en or ee
        if record is None:
            continue
        ee_title = str(ee["title"]).strip() if ee else ""
        en_title = str(en["title"]).strip() if en else ""
        if en_title and ee_title and en_title != ee_title:
            title = en_title
            langs = "en+ee"
        else:
            title = ee_title or en_title
            langs = "ee" if ee else "en"
        raw_metadata: Dict[str, Any] = {
            "provider": "yahoo_finance_rss",
            "stock_code": code,
            "langs": langs,
            "scraped": True,
        }
        if langs == "en+ee":
            raw_metadata["title_en"] = en_title
            raw_metadata["title_ee"] = ee_title
        elif langs == "ee":
            raw_metadata["title_ee"] = ee_title
        else:
            raw_metadata["title_en"] = en_title
        items.append(
            InformationItem(
                source="yahoo_ee",
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
                market=MARKET_EE,
                summary=record.get("summary"),
                effective_at=record["published"],
            )
        )
    return items
