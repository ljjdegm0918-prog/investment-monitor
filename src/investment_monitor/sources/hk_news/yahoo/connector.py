"""Yahoo Finance HK news connector for market=hk companies."""

from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Mapping, Optional, Tuple

from ....models import CollectionRequest, InformationItem, MARKET_HK
from ...hkexnews.client import normalize_hk_ticker
from .client import (
    YahooHkNewsClient,
    YahooHkNewsRequestError,
)

LOGGER = logging.getLogger(__name__)

MAX_LOOKBACK_DAYS = 30


class YahooHkNewsConnector:
    """Collect Yahoo Finance HK stock news for active HK companies."""

    name = "yahoo_hk"
    provider = "Yahoo Finance HK"
    max_lookback_days = MAX_LOOKBACK_DAYS

    def __init__(self, client: Optional[YahooHkNewsClient] = None) -> None:
        self._client = client or YahooHkNewsClient.from_environment()
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
            if market != MARKET_HK:
                LOGGER.info(
                    "yahoo_hk ticker=%s market=%s skipped not_hk_market",
                    ticker,
                    market,
                )
                continue
            code = normalize_hk_ticker(ticker)
            symbol = _yahoo_symbol(code)
            try:
                zh_records = self._client.fetch_news(
                    symbol,
                    request.start_date,
                    request.end_date,
                    lang="zh-Hant-HK",
                )
                en_records = self._client.fetch_news(
                    symbol,
                    request.start_date,
                    request.end_date,
                    lang="en-HK",
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
                    "yahoo_hk ticker=%s status=failure error=%s",
                    ticker,
                    message,
                )
        self._last_errors = tuple(failures)
        if len(request.tickers) == 1 and failures:
            raise YahooHkNewsRequestError(failures[0][1])
        return items


def _yahoo_symbol(code: str) -> str:
    """Convert a canonical HK ticker to a Yahoo symbol at request time only."""
    cleaned = str(code).strip().upper()
    if cleaned.endswith(".HK"):
        return cleaned
    digits = re.sub(r"[^0-9]", "", cleaned)
    if digits:
        # Yahoo uses at least 4 digits: 00700 -> 0700, 09988 -> 9988.
        return str(int(digits)).zfill(4) + ".HK"
    return cleaned + ".HK" if cleaned else cleaned


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
                source="yahoo_hk",
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
                market=MARKET_HK,
                summary=record.get("summary"),
                effective_at=record["published"],
            )
        )
    return items
