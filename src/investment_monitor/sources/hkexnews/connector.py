"""HKEXnews announcement connector for market=hk companies."""

from __future__ import annotations

import logging
from datetime import date, datetime, timezone
from typing import Any, Dict, List, Mapping, Optional, Tuple

from ...models import CollectionRequest, InformationItem, MARKET_HK
from .client import (
    HkexNewsClient,
    HkexNewsRequestError,
    normalize_hk_ticker,
    stable_fallback_id,
)

LOGGER = logging.getLogger(__name__)

MAX_LOOKBACK_DAYS = 30


class HkexNewsConnector:
    """Collect HKEXnews announcements for active HK companies."""

    name = "hkexnews"
    provider = "HKEXnews (HKEX)"
    max_lookback_days = MAX_LOOKBACK_DAYS
    # Key-free: no secret_fields and no configuration_error.

    def __init__(self, client: Optional[HkexNewsClient] = None) -> None:
        self._client = client or HkexNewsClient.from_environment()
        self._last_errors: Tuple[Tuple[str, str], ...] = ()

    @property
    def last_errors(self) -> Tuple[Tuple[str, str], ...]:
        """(ticker, message) pairs from the most recent collect call."""
        return self._last_errors

    def collect(self, request: CollectionRequest) -> List[InformationItem]:
        """Collect announcements per ticker; non-HK tickers skip silently."""
        items: List[InformationItem] = []
        failures: List[Tuple[str, str]] = []
        collected_at = datetime.now(timezone.utc)

        for ticker in request.tickers:
            market = request.market_for(ticker)
            if market != MARKET_HK:
                LOGGER.info(
                    "hkexnews ticker=%s market=%s skipped not_hk_market",
                    ticker,
                    market,
                )
                continue
            code = normalize_hk_ticker(ticker)
            try:
                stock_id = self._client.stock_id_for(code)
                if stock_id is None:
                    LOGGER.info(
                        "hkexnews ticker=%s no_stock_id skipped",
                        code,
                    )
                    continue
                en_records = self._client.search_disclosures(
                    stock_id,
                    request.start_date,
                    request.end_date,
                    lang="E",
                )
                zh_records = self._client.search_disclosures(
                    stock_id,
                    request.start_date,
                    request.end_date,
                    lang="zh",
                )
                items.extend(
                    _map_records(
                        en_records,
                        zh_records,
                        code=code,
                        start_date=request.start_date,
                        end_date=request.end_date,
                        collected_at=collected_at,
                    )
                )
            except Exception as error:
                message = str(error) or error.__class__.__name__
                failures.append((ticker, message))
                LOGGER.warning(
                    "hkexnews ticker=%s status=failure error=%s",
                    ticker,
                    message,
                )

        self._last_errors = tuple(failures)
        if len(request.tickers) == 1 and failures:
            raise HkexNewsRequestError(failures[0][1])
        return items


def _merge_bilingual(
    en_records: List[Mapping[str, Any]],
    zh_records: List[Mapping[str, Any]],
) -> Dict[str, Dict[str, Optional[Mapping[str, Any]]]]:
    merged: Dict[str, Dict[str, Optional[Mapping[str, Any]]]] = {}
    for record in en_records:
        key = str(record["news_id"]) or stable_fallback_id(str(record["url"]))
        merged[key] = {"en": record, "zh": None}
    for record in zh_records:
        key = str(record["news_id"]) or stable_fallback_id(str(record["url"]))
        if key in merged:
            merged[key]["zh"] = record
        else:
            merged[key] = {"en": None, "zh": record}
    return merged


def _map_records(
    en_records: List[Mapping[str, Any]],
    zh_records: List[Mapping[str, Any]],
    *,
    code: str,
    start_date: date,
    end_date: date,
    collected_at: datetime,
) -> List[InformationItem]:
    items: List[InformationItem] = []
    for key, pair in _merge_bilingual(en_records, zh_records).items():
        en = pair["en"]
        zh = pair["zh"]
        primary = en or zh
        if primary is None:
            continue
        published_at = primary["published_at"]
        if not start_date <= published_at.date() <= end_date:
            continue
        title = str((en or zh)["title"])
        url = str((en or zh)["url"])
        stock_name = str((en or zh).get("stock_name") or code)
        file_type = str((en or zh).get("file_type") or "")
        raw_metadata: Dict[str, Any] = {
            "provider": "hkexnews",
            "stock_code": code,
            "stock_name": stock_name,
            "news_id": key,
            "file_type": file_type,
            "file_link": str((en or zh).get("file_link") or ""),
            "langs": "en+zh" if (en and zh) else ("en" if en else "zh"),
        }
        if en is not None:
            raw_metadata["title_en"] = str(en["title"])
        if zh is not None:
            raw_metadata["title_zh"] = str(zh["title"])
        items.append(
            InformationItem(
                source="hkexnews",
                source_type="regulatory_filing",
                external_id=key,
                tickers=(code,),
                issuer=stock_name,
                published_at=published_at,
                title=title,
                document_type="hkex_announcement",
                url=url,
                collected_at=collected_at,
                raw_metadata=raw_metadata,
                market=MARKET_HK,
                summary=None,
                effective_at=published_at,
            )
        )
    return items
