"""Yahoo Finance SG news connector for market=sg companies."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Mapping, Optional, Tuple

from ....models import CollectionRequest, InformationItem, MARKET_SG
from ....web_repository import normalize_sg_ticker
from ..symbols import sg_yahoo_symbol
from .client import (
    YahooSgNewsClient,
    YahooSgNewsRequestError,
)

LOGGER = logging.getLogger(__name__)

MAX_LOOKBACK_DAYS = 30


class YahooSgNewsConnector:
    """Collect Yahoo Finance Singapore stock news for market=sg companies."""

    name = "yahoo_sg"
    provider = "Yahoo Finance SG"
    max_lookback_days = MAX_LOOKBACK_DAYS

    def __init__(
        self,
        client: Optional[YahooSgNewsClient] = None,
        symbol_for: Optional[Callable[[str], str]] = None,
    ) -> None:
        self._client = client or YahooSgNewsClient.from_environment()
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
            if market != MARKET_SG:
                LOGGER.info(
                    "yahoo_sg ticker=%s market=%s skipped not_sg_market",
                    ticker,
                    market,
                )
                continue
            code = normalize_sg_ticker(ticker)
            symbol = self._symbol_for(code)
            try:
                sg_records = self._client.fetch_news(
                    symbol,
                    request.start_date,
                    request.end_date,
                    lang="en-SG",
                )
                en_records = self._client.fetch_news(
                    symbol,
                    request.start_date,
                    request.end_date,
                    lang="en-US",
                )
                items.extend(
                    _map_news(
                        sg_records,
                        en_records,
                        code=code,
                        collected_at=collected_at,
                    )
                )
            except Exception as error:
                message = str(error) or error.__class__.__name__
                failures.append((ticker, message))
                LOGGER.warning(
                    "yahoo_sg ticker=%s status=failure error=%s",
                    ticker,
                    message,
                )
        self._last_errors = tuple(failures)
        if len(request.tickers) == 1 and failures:
            raise YahooSgNewsRequestError(failures[0][1])
        return items


def _default_symbol_for(ticker: str) -> str:
    """Request-time symbol: canonical SG root plus the .SI suffix."""
    return sg_yahoo_symbol(ticker)


def _map_news(
    sg_records: List[Mapping[str, Any]],
    en_records: List[Mapping[str, Any]],
    *,
    code: str,
    collected_at: datetime,
) -> List[InformationItem]:
    merged: Dict[str, Dict[str, Optional[Mapping[str, Any]]]] = {}
    for record in sg_records:
        merged[str(record["external_id"])] = {"sg": record, "en": None}
    for record in en_records:
        key = str(record["external_id"])
        if key in merged:
            merged[key]["en"] = record
        else:
            merged[key] = {"sg": None, "en": record}

    items: List[InformationItem] = []
    for key, pair in merged.items():
        sg = pair["sg"]
        en = pair["en"]
        record = en or sg
        if record is None:
            continue
        sg_title = str(sg["title"]).strip() if sg else ""
        en_title = str(en["title"]).strip() if en else ""
        if en_title and sg_title and en_title != sg_title:
            title = en_title
            langs = "en+sg"
        else:
            title = sg_title or en_title
            langs = "sg" if sg else "en"
        raw_metadata: Dict[str, Any] = {
            "provider": "yahoo_finance_rss",
            "stock_code": code,
            "langs": langs,
            "scraped": True,
        }
        if langs == "en+sg":
            raw_metadata["title_en"] = en_title
            raw_metadata["title_sg"] = sg_title
        elif langs == "sg":
            raw_metadata["title_sg"] = sg_title
        else:
            raw_metadata["title_en"] = en_title
        items.append(
            InformationItem(
                source="yahoo_sg",
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
                market=MARKET_SG,
                summary=record.get("summary"),
                effective_at=record["published"],
            )
        )
    return items
