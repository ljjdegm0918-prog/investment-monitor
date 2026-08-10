"""Yahoo Finance BE news connector for market=be companies."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Mapping, Optional, Tuple

from ....models import CollectionRequest, InformationItem, MARKET_BE
from ....web_repository import normalize_be_ticker
from ..symbols import be_yahoo_symbol
from .client import (
    YahooBeNewsClient,
    YahooBeNewsRequestError,
)

LOGGER = logging.getLogger(__name__)

MAX_LOOKBACK_DAYS = 30


class YahooBeNewsConnector:
    """Collect Yahoo Finance Belgium stock news for market=be companies."""

    name = "yahoo_be"
    provider = "Yahoo Finance BE"
    max_lookback_days = MAX_LOOKBACK_DAYS

    def __init__(
        self,
        client: Optional[YahooBeNewsClient] = None,
        symbol_for: Optional[Callable[[str], str]] = None,
    ) -> None:
        self._client = client or YahooBeNewsClient.from_environment()
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
            if market != MARKET_BE:
                LOGGER.info(
                    "yahoo_be ticker=%s market=%s skipped not_be_market",
                    ticker,
                    market,
                )
                continue
            code = normalize_be_ticker(ticker)
            symbol = self._symbol_for(code)
            try:
                fr_records = self._client.fetch_news(
                    symbol,
                    request.start_date,
                    request.end_date,
                    lang="fr-BE",
                )
                en_records = self._client.fetch_news(
                    symbol,
                    request.start_date,
                    request.end_date,
                    lang="en-US",
                )
                items.extend(
                    _map_news(
                        fr_records,
                        en_records,
                        code=code,
                        collected_at=collected_at,
                    )
                )
            except Exception as error:
                message = str(error) or error.__class__.__name__
                failures.append((ticker, message))
                LOGGER.warning(
                    "yahoo_be ticker=%s status=failure error=%s",
                    ticker,
                    message,
                )
        self._last_errors = tuple(failures)
        if len(request.tickers) == 1 and failures:
            raise YahooBeNewsRequestError(failures[0][1])
        return items


def _default_symbol_for(ticker: str) -> str:
    """Request-time symbol: canonical BE root plus the .BR suffix."""
    return be_yahoo_symbol(ticker)


def _map_news(
    fr_records: List[Mapping[str, Any]],
    en_records: List[Mapping[str, Any]],
    *,
    code: str,
    collected_at: datetime,
) -> List[InformationItem]:
    merged: Dict[str, Dict[str, Optional[Mapping[str, Any]]]] = {}
    for record in fr_records:
        merged[str(record["external_id"])] = {"fr": record, "en": None}
    for record in en_records:
        key = str(record["external_id"])
        if key in merged:
            merged[key]["en"] = record
        else:
            merged[key] = {"fr": None, "en": record}

    items: List[InformationItem] = []
    for key, pair in merged.items():
        fr = pair["fr"]
        en = pair["en"]
        record = en or fr
        if record is None:
            continue
        fr_title = str(fr["title"]).strip() if fr else ""
        en_title = str(en["title"]).strip() if en else ""
        if en_title and fr_title and en_title != fr_title:
            title = en_title
            langs = "en+fr"
        else:
            # Identical titles are never claimed as bilingual: live recon
            # (2026-08-10) shows Yahoo region=BE lang=fr-BE returns the same
            # English items as lang=en-US, so identical titles stay "en".
            title = fr_title or en_title
            langs = "en" if en or not fr else "fr"
        raw_metadata: Dict[str, Any] = {
            "provider": "yahoo_finance_rss",
            "stock_code": code,
            "langs": langs,
            "scraped": True,
        }
        if langs == "en+fr":
            raw_metadata["title_en"] = en_title
            raw_metadata["title_fr"] = fr_title
        elif langs == "fr":
            raw_metadata["title_fr"] = fr_title
        else:
            raw_metadata["title_en"] = en_title
        items.append(
            InformationItem(
                source="yahoo_be",
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
                market=MARKET_BE,
                summary=record.get("summary"),
                effective_at=record["published"],
            )
        )
    return items
