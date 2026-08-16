"""Yahoo Finance MX news connector for market=mx companies."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Mapping, Optional, Tuple

from ....models import CollectionRequest, InformationItem, MARKET_MX
from ....web_repository import normalize_mx_ticker
from ..symbols import mx_yahoo_symbol
from .client import (
    YahooMxNewsClient,
    YahooMxNewsRequestError,
)

LOGGER = logging.getLogger(__name__)

MAX_LOOKBACK_DAYS = 30


class YahooMxNewsConnector:
    """Collect Yahoo Finance Mexico stock news for market=mx companies."""

    name = "yahoo_mx"
    provider = "Yahoo Finance MX"
    max_lookback_days = MAX_LOOKBACK_DAYS

    def __init__(
        self,
        client: Optional[YahooMxNewsClient] = None,
        symbol_for: Optional[Callable[[str], str]] = None,
    ) -> None:
        self._client = client or YahooMxNewsClient.from_environment()
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
            if market != MARKET_MX:
                LOGGER.info(
                    "yahoo_mx ticker=%s market=%s skipped not_mx_market",
                    ticker,
                    market,
                )
                continue
            code = normalize_mx_ticker(ticker)
            symbol = self._symbol_for(code)
            try:
                mx_records = self._client.fetch_news(
                    symbol,
                    request.start_date,
                    request.end_date,
                    lang="es-MX",
                )
                en_records = self._client.fetch_news(
                    symbol,
                    request.start_date,
                    request.end_date,
                    lang="en-US",
                )
                items.extend(
                    _map_news(
                        mx_records,
                        en_records,
                        code=code,
                        collected_at=collected_at,
                    )
                )
            except Exception as error:
                message = str(error) or error.__class__.__name__
                failures.append((ticker, message))
                LOGGER.warning(
                    "yahoo_mx ticker=%s status=failure error=%s",
                    ticker,
                    message,
                )
        self._last_errors = tuple(failures)
        if len(request.tickers) == 1 and failures:
            raise YahooMxNewsRequestError(failures[0][1])
        return items


def _default_symbol_for(ticker: str) -> str:
    """Request-time symbol: canonical MX root plus the .MX suffix."""
    return mx_yahoo_symbol(ticker)


def _map_news(
    mx_records: List[Mapping[str, Any]],
    en_records: List[Mapping[str, Any]],
    *,
    code: str,
    collected_at: datetime,
) -> List[InformationItem]:
    merged: Dict[str, Dict[str, Optional[Mapping[str, Any]]]] = {}
    for record in mx_records:
        merged[str(record["external_id"])] = {"mx": record, "en": None}
    for record in en_records:
        key = str(record["external_id"])
        if key in merged:
            merged[key]["en"] = record
        else:
            merged[key] = {"mx": None, "en": record}

    items: List[InformationItem] = []
    for key, pair in merged.items():
        mx = pair["mx"]
        en = pair["en"]
        record = en or mx
        if record is None:
            continue
        mx_title = str(mx["title"]).strip() if mx else ""
        en_title = str(en["title"]).strip() if en else ""
        if en_title and mx_title and en_title != mx_title:
            title = en_title
            langs = "en+mx"
        else:
            title = mx_title or en_title
            langs = "mx" if mx else "en"
        raw_metadata: Dict[str, Any] = {
            "provider": "yahoo_finance_rss",
            "stock_code": code,
            "langs": langs,
            "scraped": True,
        }
        if langs == "en+mx":
            raw_metadata["title_en"] = en_title
            raw_metadata["title_mx"] = mx_title
        elif langs == "mx":
            raw_metadata["title_mx"] = mx_title
        else:
            raw_metadata["title_en"] = en_title
        items.append(
            InformationItem(
                source="yahoo_mx",
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
                market=MARKET_MX,
                summary=record.get("summary"),
                effective_at=record["published"],
            )
        )
    return items
