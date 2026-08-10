"""Yahoo Finance PL news connector for market=pl companies."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Mapping, Optional, Tuple

from ....models import CollectionRequest, InformationItem, MARKET_PL
from ....web_repository import normalize_pl_ticker
from ..symbols import pl_yahoo_symbol
from .client import (
    YahooPlNewsClient,
    YahooPlNewsRequestError,
)

LOGGER = logging.getLogger(__name__)

MAX_LOOKBACK_DAYS = 30


class YahooPlNewsConnector:
    """Collect Yahoo Finance Poland stock news for market=pl companies."""

    name = "yahoo_pl"
    provider = "Yahoo Finance PL"
    max_lookback_days = MAX_LOOKBACK_DAYS

    def __init__(
        self,
        client: Optional[YahooPlNewsClient] = None,
        symbol_for: Optional[Callable[[str], str]] = None,
    ) -> None:
        self._client = client or YahooPlNewsClient.from_environment()
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
            if market != MARKET_PL:
                LOGGER.info(
                    "yahoo_pl ticker=%s market=%s skipped not_pl_market",
                    ticker,
                    market,
                )
                continue
            code = normalize_pl_ticker(ticker)
            symbol = self._symbol_for(code)
            try:
                pl_records = self._client.fetch_news(
                    symbol,
                    request.start_date,
                    request.end_date,
                    lang="pl-PL",
                )
                en_records = self._client.fetch_news(
                    symbol,
                    request.start_date,
                    request.end_date,
                    lang="en-US",
                )
                items.extend(
                    _map_news(
                        pl_records,
                        en_records,
                        code=code,
                        collected_at=collected_at,
                    )
                )
            except Exception as error:
                message = str(error) or error.__class__.__name__
                failures.append((ticker, message))
                LOGGER.warning(
                    "yahoo_pl ticker=%s status=failure error=%s",
                    ticker,
                    message,
                )
        self._last_errors = tuple(failures)
        if len(request.tickers) == 1 and failures:
            raise YahooPlNewsRequestError(failures[0][1])
        return items


def _default_symbol_for(ticker: str) -> str:
    """Request-time symbol: canonical PL root plus the .WA suffix."""
    return pl_yahoo_symbol(ticker)


def _map_news(
    pl_records: List[Mapping[str, Any]],
    en_records: List[Mapping[str, Any]],
    *,
    code: str,
    collected_at: datetime,
) -> List[InformationItem]:
    merged: Dict[str, Dict[str, Optional[Mapping[str, Any]]]] = {}
    for record in pl_records:
        merged[str(record["external_id"])] = {"pl": record, "en": None}
    for record in en_records:
        key = str(record["external_id"])
        if key in merged:
            merged[key]["en"] = record
        else:
            merged[key] = {"pl": None, "en": record}

    items: List[InformationItem] = []
    for key, pair in merged.items():
        pl = pair["pl"]
        en = pair["en"]
        record = en or pl
        if record is None:
            continue
        pl_title = str(pl["title"]).strip() if pl else ""
        en_title = str(en["title"]).strip() if en else ""
        if en_title and pl_title and en_title != pl_title:
            title = en_title
            langs = "en+pl"
        else:
            title = pl_title or en_title
            langs = "pl" if pl else "en"
        raw_metadata: Dict[str, Any] = {
            "provider": "yahoo_finance_rss",
            "stock_code": code,
            "langs": langs,
            "scraped": True,
        }
        if langs == "en+pl":
            raw_metadata["title_en"] = en_title
            raw_metadata["title_pl"] = pl_title
        elif langs == "pl":
            raw_metadata["title_pl"] = pl_title
        else:
            raw_metadata["title_en"] = en_title
        items.append(
            InformationItem(
                source="yahoo_pl",
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
                market=MARKET_PL,
                summary=record.get("summary"),
                effective_at=record["published"],
            )
        )
    return items
