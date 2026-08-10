"""Yahoo Finance CH news connector for market=ch companies."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Mapping, Optional, Tuple

from ....models import CollectionRequest, InformationItem, MARKET_CH
from ....web_repository import normalize_ch_ticker
from ..symbols import ch_yahoo_symbol
from .client import (
    YahooChNewsClient,
    YahooChNewsRequestError,
)

LOGGER = logging.getLogger(__name__)

MAX_LOOKBACK_DAYS = 30


class YahooChNewsConnector:
    """Collect Yahoo Finance Switzerland stock news for market=ch companies."""

    name = "yahoo_ch"
    provider = "Yahoo Finance CH"
    max_lookback_days = MAX_LOOKBACK_DAYS

    def __init__(
        self,
        client: Optional[YahooChNewsClient] = None,
        symbol_for: Optional[Callable[[str], str]] = None,
    ) -> None:
        self._client = client or YahooChNewsClient.from_environment()
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
            if market != MARKET_CH:
                LOGGER.info(
                    "yahoo_ch ticker=%s market=%s skipped not_ch_market",
                    ticker,
                    market,
                )
                continue
            code = normalize_ch_ticker(ticker)
            symbol = self._symbol_for(code)
            try:
                de_records = self._client.fetch_news(
                    symbol,
                    request.start_date,
                    request.end_date,
                    lang="de-CH",
                )
                en_records = self._client.fetch_news(
                    symbol,
                    request.start_date,
                    request.end_date,
                    lang="en-US",
                )
                items.extend(
                    _map_news(
                        de_records,
                        en_records,
                        code=code,
                        collected_at=collected_at,
                    )
                )
            except Exception as error:
                message = str(error) or error.__class__.__name__
                failures.append((ticker, message))
                LOGGER.warning(
                    "yahoo_ch ticker=%s status=failure error=%s",
                    ticker,
                    message,
                )
        self._last_errors = tuple(failures)
        if len(request.tickers) == 1 and failures:
            raise YahooChNewsRequestError(failures[0][1])
        return items


def _default_symbol_for(ticker: str) -> str:
    """Request-time symbol: canonical CH root plus the .SW suffix."""
    return ch_yahoo_symbol(ticker)


def _map_news(
    de_records: List[Mapping[str, Any]],
    en_records: List[Mapping[str, Any]],
    *,
    code: str,
    collected_at: datetime,
) -> List[InformationItem]:
    merged: Dict[str, Dict[str, Optional[Mapping[str, Any]]]] = {}
    for record in de_records:
        merged[str(record["external_id"])] = {"de": record, "en": None}
    for record in en_records:
        key = str(record["external_id"])
        if key in merged:
            merged[key]["en"] = record
        else:
            merged[key] = {"de": None, "en": record}

    items: List[InformationItem] = []
    for key, pair in merged.items():
        de = pair["de"]
        en = pair["en"]
        record = en or de
        if record is None:
            continue
        de_title = str(de["title"]).strip() if de else ""
        en_title = str(en["title"]).strip() if en else ""
        if en_title and de_title and en_title != de_title:
            title = en_title
            langs = "en+de"
        else:
            title = de_title or en_title
            langs = "de" if de else "en"
        raw_metadata: Dict[str, Any] = {
            "provider": "yahoo_finance_rss",
            "stock_code": code,
            "langs": langs,
            "scraped": True,
        }
        if langs == "en+de":
            raw_metadata["title_en"] = en_title
            raw_metadata["title_de"] = de_title
        elif langs == "de":
            raw_metadata["title_de"] = de_title
        else:
            raw_metadata["title_en"] = en_title
        items.append(
            InformationItem(
                source="yahoo_ch",
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
                market=MARKET_CH,
                summary=record.get("summary"),
                effective_at=record["published"],
            )
        )
    return items
