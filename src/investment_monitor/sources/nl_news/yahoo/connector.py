"""Yahoo Finance NL news connector for market=nl companies."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Mapping, Optional, Tuple

from ....models import CollectionRequest, InformationItem, MARKET_NL
from ....web_repository import normalize_nl_ticker
from ..symbols import nl_yahoo_symbol
from .client import (
    YahooNlNewsClient,
    YahooNlNewsRequestError,
)

LOGGER = logging.getLogger(__name__)

MAX_LOOKBACK_DAYS = 30


class YahooNlNewsConnector:
    """Collect Yahoo Finance Netherlands stock news for market=nl companies."""

    name = "yahoo_nl"
    provider = "Yahoo Finance NL"
    max_lookback_days = MAX_LOOKBACK_DAYS

    def __init__(
        self,
        client: Optional[YahooNlNewsClient] = None,
        symbol_for: Optional[Callable[[str], str]] = None,
    ) -> None:
        self._client = client or YahooNlNewsClient.from_environment()
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
            if market != MARKET_NL:
                LOGGER.info(
                    "yahoo_nl ticker=%s market=%s skipped not_nl_market",
                    ticker,
                    market,
                )
                continue
            code = normalize_nl_ticker(ticker)
            symbol = self._symbol_for(code)
            try:
                nl_records = self._client.fetch_news(
                    symbol,
                    request.start_date,
                    request.end_date,
                    lang="nl-NL",
                )
                en_records = self._client.fetch_news(
                    symbol,
                    request.start_date,
                    request.end_date,
                    lang="en-US",
                )
                items.extend(
                    _map_news(
                        nl_records,
                        en_records,
                        code=code,
                        collected_at=collected_at,
                    )
                )
            except Exception as error:
                message = str(error) or error.__class__.__name__
                failures.append((ticker, message))
                LOGGER.warning(
                    "yahoo_nl ticker=%s status=failure error=%s",
                    ticker,
                    message,
                )
        self._last_errors = tuple(failures)
        if len(request.tickers) == 1 and failures:
            raise YahooNlNewsRequestError(failures[0][1])
        return items


def _default_symbol_for(ticker: str) -> str:
    """Request-time symbol: canonical NL root plus the .AS suffix."""
    return nl_yahoo_symbol(ticker)


def _map_news(
    nl_records: List[Mapping[str, Any]],
    en_records: List[Mapping[str, Any]],
    *,
    code: str,
    collected_at: datetime,
) -> List[InformationItem]:
    merged: Dict[str, Dict[str, Optional[Mapping[str, Any]]]] = {}
    for record in nl_records:
        merged[str(record["external_id"])] = {"nl": record, "en": None}
    for record in en_records:
        key = str(record["external_id"])
        if key in merged:
            merged[key]["en"] = record
        else:
            merged[key] = {"nl": None, "en": record}

    items: List[InformationItem] = []
    for key, pair in merged.items():
        nl = pair["nl"]
        en = pair["en"]
        record = en or nl
        if record is None:
            continue
        nl_title = str(nl["title"]).strip() if nl else ""
        en_title = str(en["title"]).strip() if en else ""
        if en_title and nl_title and en_title != nl_title:
            title = en_title
            langs = "en+nl"
        else:
            title = nl_title or en_title
            langs = "nl" if nl else "en"
        raw_metadata: Dict[str, Any] = {
            "provider": "yahoo_finance_rss",
            "stock_code": code,
            "langs": langs,
            "scraped": True,
        }
        if langs == "en+nl":
            raw_metadata["title_en"] = en_title
            raw_metadata["title_nl"] = nl_title
        elif langs == "nl":
            raw_metadata["title_nl"] = nl_title
        else:
            raw_metadata["title_en"] = en_title
        items.append(
            InformationItem(
                source="yahoo_nl",
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
                market=MARKET_NL,
                summary=record.get("summary"),
                effective_at=record["published"],
            )
        )
    return items
