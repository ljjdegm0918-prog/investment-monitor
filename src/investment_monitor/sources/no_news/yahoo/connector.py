"""Yahoo Finance NO news connector for market=no companies."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Mapping, Optional, Tuple

from ....models import CollectionRequest, InformationItem, MARKET_NO
from ....web_repository import normalize_no_ticker
from ..symbols import no_yahoo_symbol
from .client import (
    YahooNoNewsClient,
    YahooNoNewsRequestError,
)

LOGGER = logging.getLogger(__name__)

MAX_LOOKBACK_DAYS = 30


class YahooNoNewsConnector:
    """Collect Yahoo Finance Norway stock news for market=no companies."""

    name = "yahoo_no"
    provider = "Yahoo Finance NO"
    max_lookback_days = MAX_LOOKBACK_DAYS

    def __init__(
        self,
        client: Optional[YahooNoNewsClient] = None,
        symbol_for: Optional[Callable[[str], str]] = None,
    ) -> None:
        self._client = client or YahooNoNewsClient.from_environment()
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
            if market != MARKET_NO:
                LOGGER.info(
                    "yahoo_no ticker=%s market=%s skipped not_no_market",
                    ticker,
                    market,
                )
                continue
            code = normalize_no_ticker(ticker)
            symbol = self._symbol_for(code)
            try:
                no_records = self._client.fetch_news(
                    symbol,
                    request.start_date,
                    request.end_date,
                    lang="nb-NO",
                )
                en_records = self._client.fetch_news(
                    symbol,
                    request.start_date,
                    request.end_date,
                    lang="en-US",
                )
                items.extend(
                    _map_news(
                        no_records,
                        en_records,
                        code=code,
                        collected_at=collected_at,
                    )
                )
            except Exception as error:
                message = str(error) or error.__class__.__name__
                failures.append((ticker, message))
                LOGGER.warning(
                    "yahoo_no ticker=%s status=failure error=%s",
                    ticker,
                    message,
                )
        self._last_errors = tuple(failures)
        if len(request.tickers) == 1 and failures:
            raise YahooNoNewsRequestError(failures[0][1])
        return items


def _default_symbol_for(ticker: str) -> str:
    """Request-time symbol: canonical NO root plus the .OL suffix."""
    return no_yahoo_symbol(ticker)


def _map_news(
    no_records: List[Mapping[str, Any]],
    en_records: List[Mapping[str, Any]],
    *,
    code: str,
    collected_at: datetime,
) -> List[InformationItem]:
    merged: Dict[str, Dict[str, Optional[Mapping[str, Any]]]] = {}
    for record in no_records:
        merged[str(record["external_id"])] = {"no": record, "en": None}
    for record in en_records:
        key = str(record["external_id"])
        if key in merged:
            merged[key]["en"] = record
        else:
            merged[key] = {"no": None, "en": record}

    items: List[InformationItem] = []
    for key, pair in merged.items():
        no = pair["no"]
        en = pair["en"]
        record = en or no
        if record is None:
            continue
        no_title = str(no["title"]).strip() if no else ""
        en_title = str(en["title"]).strip() if en else ""
        if en_title and no_title and en_title != no_title:
            title = en_title
            langs = "en+no"
        else:
            title = no_title or en_title
            langs = "no" if no else "en"
        raw_metadata: Dict[str, Any] = {
            "provider": "yahoo_finance_rss",
            "stock_code": code,
            "langs": langs,
            "scraped": True,
        }
        if langs == "en+no":
            raw_metadata["title_en"] = en_title
            raw_metadata["title_no"] = no_title
        elif langs == "no":
            raw_metadata["title_no"] = no_title
        else:
            raw_metadata["title_en"] = en_title
        items.append(
            InformationItem(
                source="yahoo_no",
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
                market=MARKET_NO,
                summary=record.get("summary"),
                effective_at=record["published"],
            )
        )
    return items
