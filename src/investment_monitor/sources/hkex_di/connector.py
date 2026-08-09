"""HKEX Disclosure of Interests (DI) connector for market=hk companies."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Mapping, Optional, Tuple

from ...models import CollectionRequest, InformationItem, MARKET_HK
from ..hkexnews.client import normalize_hk_ticker
from .client import (
    HkexDiClient,
    HkexDiRequestError,
    stable_di_id,
)

LOGGER = logging.getLogger(__name__)

MAX_LOOKBACK_DAYS = 30


class HkexDiConnector:
    """Collect HKEX DI notices for active HK companies (archive search)."""

    name = "hkex_di"
    provider = "Disclosure of Interests (HKEX)"
    max_lookback_days = MAX_LOOKBACK_DAYS
    # Key-free: no secret_fields and no configuration_error.

    def __init__(self, client: Optional[HkexDiClient] = None) -> None:
        self._client = client or HkexDiClient.from_environment()
        self._last_errors: Tuple[Tuple[str, str], ...] = ()

    @property
    def last_errors(self) -> Tuple[Tuple[str, str], ...]:
        """(ticker, message) pairs from the most recent collect call."""
        return self._last_errors

    def collect(self, request: CollectionRequest) -> List[InformationItem]:
        """Collect DI notices per ticker; non-HK tickers skip silently."""
        items: List[InformationItem] = []
        failures: List[Tuple[str, str]] = []
        collected_at = datetime.now(timezone.utc)
        for ticker in request.tickers:
            market = request.market_for(ticker)
            if market != MARKET_HK:
                LOGGER.info(
                    "hkex_di ticker=%s market=%s skipped not_hk_market",
                    ticker,
                    market,
                )
                continue
            code = normalize_hk_ticker(ticker)
            try:
                en_records = self._client.search_disclosures(
                    code,
                    request.start_date,
                    request.end_date,
                    lang="EN",
                )
                zh_records = self._client.search_disclosures(
                    code,
                    request.start_date,
                    request.end_date,
                    lang="ZH",
                )
                items.extend(
                    _map_records(
                        en_records,
                        zh_records,
                        code=code,
                        collected_at=collected_at,
                    )
                )
            except Exception as error:
                message = str(error) or error.__class__.__name__
                failures.append((ticker, message))
                LOGGER.warning(
                    "hkex_di ticker=%s status=failure error=%s",
                    ticker,
                    message,
                )
        self._last_errors = tuple(failures)
        if len(request.tickers) == 1 and failures:
            raise HkexDiRequestError(failures[0][1])
        return items


def _merge_records(
    en_records: List[Mapping[str, Any]],
    zh_records: List[Mapping[str, Any]],
) -> Dict[str, Dict[str, Optional[Mapping[str, Any]]]]:
    def key(record: Mapping[str, Any]) -> str:
        serial = str(record.get("serial") or "").strip()
        if serial:
            return serial
        return stable_di_id(
            str(record.get("url") or ""),
            str(record.get("date_text") or ""),
            str(record.get("person") or ""),
        )

    merged: Dict[str, Dict[str, Optional[Mapping[str, Any]]]] = {}
    for record in en_records:
        merged[key(record)] = {"en": record, "zh": None}
    for record in zh_records:
        record_key = key(record)
        if record_key in merged:
            merged[record_key]["zh"] = record
        else:
            merged[record_key] = {"en": None, "zh": record}
    return merged


def _map_records(
    en_records: List[Mapping[str, Any]],
    zh_records: List[Mapping[str, Any]],
    *,
    code: str,
    collected_at: datetime,
) -> List[InformationItem]:
    items: List[InformationItem] = []
    for key, pair in _merge_records(en_records, zh_records).items():
        en = pair["en"]
        zh = pair["zh"]
        record = en or zh
        if record is None:
            continue
        en_title = str(en.get("title") or "").strip() if en else ""
        zh_title = str(zh.get("title") or "").strip() if zh else ""
        if en_title and zh_title and en_title != zh_title:
            title = en_title
            langs = "en+zh"
        else:
            title = en_title or zh_title
            langs = "en" if en else "zh"
        raw_metadata: Dict[str, Any] = {
            "provider": "hkex_di",
            "stock_code": code,
            "serial": str(record.get("serial") or ""),
            "person": str(record.get("person") or ""),
            "reason": str(record.get("reason") or ""),
            "shares": str(record.get("shares") or ""),
            "pct": str(record.get("pct") or ""),
            "langs": langs,
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
                source="hkex_di",
                source_type="regulatory_filing",
                external_id=key,
                tickers=(code,),
                issuer=str(record.get("stock_name") or code),
                published_at=record["published_at"],
                title=title,
                document_type="di_notice",
                url=str(record["url"]),
                collected_at=collected_at,
                raw_metadata=raw_metadata,
                market=MARKET_HK,
                summary=None,
                effective_at=record["published_at"],
            )
        )
    return items
