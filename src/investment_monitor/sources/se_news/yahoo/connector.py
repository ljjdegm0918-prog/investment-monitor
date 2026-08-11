"""Yahoo Finance SE news connector for market=se companies."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Mapping, Optional, Tuple

from ....models import CollectionRequest, InformationItem, MARKET_SE
from ....web_repository import normalize_se_ticker
from ..symbols import se_yahoo_symbol
from .client import (
    YahooSeNewsClient,
    YahooSeNewsRequestError,
)

LOGGER = logging.getLogger(__name__)

MAX_LOOKBACK_DAYS = 30


class YahooSeNewsConnector:
    """Collect Yahoo Finance Sweden stock news for market=se companies."""

    name = "yahoo_se"
    provider = "Yahoo Finance SE"
    max_lookback_days = MAX_LOOKBACK_DAYS

    def __init__(
        self,
        client: Optional[YahooSeNewsClient] = None,
        symbol_for: Optional[Callable[[str], str]] = None,
    ) -> None:
        self._client = client or YahooSeNewsClient.from_environment()
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
            if market != MARKET_SE:
                LOGGER.info(
                    "yahoo_se ticker=%s market=%s skipped not_se_market",
                    ticker,
                    market,
                )
                continue
            code = normalize_se_ticker(ticker)
            symbol = self._symbol_for(code)
            try:
                sv_records = self._client.fetch_news(
                    symbol,
                    request.start_date,
                    request.end_date,
                    lang="sv-SE",
                )
                en_records = self._client.fetch_news(
                    symbol,
                    request.start_date,
                    request.end_date,
                    lang="en-US",
                )
                items.extend(
                    _map_news(
                        sv_records,
                        en_records,
                        code=code,
                        collected_at=collected_at,
                    )
                )
            except Exception as error:
                message = str(error) or error.__class__.__name__
                failures.append((ticker, message))
                LOGGER.warning(
                    "yahoo_se ticker=%s status=failure error=%s",
                    ticker,
                    message,
                )
        self._last_errors = tuple(failures)
        if len(request.tickers) == 1 and failures:
            raise YahooSeNewsRequestError(failures[0][1])
        return items


def _default_symbol_for(ticker: str) -> str:
    """Request-time symbol: canonical SE root plus the .ST suffix."""
    return se_yahoo_symbol(ticker)


def _map_news(
    sv_records: List[Mapping[str, Any]],
    en_records: List[Mapping[str, Any]],
    *,
    code: str,
    collected_at: datetime,
) -> List[InformationItem]:
    merged: Dict[str, Dict[str, Optional[Mapping[str, Any]]]] = {}
    for record in sv_records:
        merged[str(record["external_id"])] = {"sv": record, "en": None}
    for record in en_records:
        key = str(record["external_id"])
        if key in merged:
            merged[key]["en"] = record
        else:
            merged[key] = {"sv": None, "en": record}

    items: List[InformationItem] = []
    for key, pair in merged.items():
        sv = pair["sv"]
        en = pair["en"]
        record = en or sv
        if record is None:
            continue
        sv_title = str(sv["title"]).strip() if sv else ""
        en_title = str(en["title"]).strip() if en else ""
        if en_title and sv_title and en_title != sv_title:
            title = en_title
            langs = "en+sv"
        else:
            title = sv_title or en_title
            langs = "sv" if sv else "en"
        raw_metadata: Dict[str, Any] = {
            "provider": "yahoo_finance_rss",
            "stock_code": code,
            "langs": langs,
            "scraped": True,
        }
        if langs == "en+sv":
            raw_metadata["title_en"] = en_title
            raw_metadata["title_sv"] = sv_title
        elif langs == "sv":
            raw_metadata["title_sv"] = sv_title
        else:
            raw_metadata["title_en"] = en_title
        items.append(
            InformationItem(
                source="yahoo_se",
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
                market=MARKET_SE,
                summary=record.get("summary"),
                effective_at=record["published"],
            )
        )
    return items
