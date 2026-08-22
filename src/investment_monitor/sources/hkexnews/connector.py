"""HKEXnews announcement connector for market=hk companies."""

from __future__ import annotations

import logging
from datetime import date, datetime, timezone
from typing import Any, Dict, List, Mapping, Optional, Tuple

from ...models import CollectionRequest, InformationItem, MARKET_HK
from ...provenance import build_raw_provenance
from .client import (
    HkexNewsClient,
    HkexNewsDataError,
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
    coverage_level = "official_public_title_search"
    # Key-free: no secret_fields and no configuration_error.

    def __init__(self, client: Optional[HkexNewsClient] = None) -> None:
        self._client = client or HkexNewsClient.from_environment()
        self._last_errors: Tuple[Tuple[str, str], ...] = ()
        self._last_collection_status = "empty"

    @property
    def last_errors(self) -> Tuple[Tuple[str, str], ...]:
        """(ticker, message) pairs from the most recent collect call."""
        return self._last_errors

    @property
    def last_collection_status(self) -> str:
        """Outcome of the latest call; never report a malformed response as empty."""
        return self._last_collection_status

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
                    raise HkexNewsDataError(
                        f"HKEXnews active/inactive security lists have no stock id for {code}."
                    )
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
                if not en_records and not zh_records:
                    failures.append((ticker, "empty_packet"))
                    LOGGER.warning(
                        "hkexnews ticker=%s status=failure error=empty_packet",
                        ticker,
                    )
                    continue
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
        if failures:
            self._last_collection_status = "partial" if items else "failure"
        else:
            self._last_collection_status = "success" if items else "empty"
        targets = sum(request.market_for(ticker) == MARKET_HK for ticker in request.tickers)
        if targets == 1 and failures:
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
        for language, record in (("English", en), ("Chinese", zh)):
            if record is not None and normalize_hk_ticker(
                str(record["stock_code"])
            ) != code:
                raise HkexNewsDataError(
                    "HKEXnews "
                    f"{language} result NEWS_ID={key} did not match requested stock code {code}."
                )
        published_at = primary["published_at"]
        if not start_date <= published_at.date() <= end_date:
            continue
        title = str(primary["title"])
        url = str(primary["url"])
        stock_name = str(primary.get("stock_name") or code)
        file_type = str(primary.get("file_type") or "")
        raw_metadata: Dict[str, Any] = {
            **build_raw_provenance(
                official_source_id=key,
                official_source_url=url,
                retrieval_url="https://www1.hkexnews.hk/search/titlesearch.xhtml",
                raw_payload={"english": en, "chinese": zh},
                raw_payload_format="json",
                classification_code=file_type or None,
                classification_label="HKEX announcement",
                published_at_raw=str(published_at),
                published_timezone="Asia/Hong_Kong",
            ),
            "provider": "hkexnews",
            "coverage_level": "official_public_title_search",
            "stock_code": code,
            "stock_name": stock_name,
            "news_id": key,
            "file_type": file_type,
            "file_link": str(primary.get("file_link") or ""),
            "official_document_url": url,
            "langs": "en+zh" if (en and zh) else ("en" if en else "zh"),
        }
        if en is not None:
            raw_metadata["title_en"] = str(en["title"])
            raw_metadata["raw_announcement_en"] = dict(en)
        if zh is not None:
            raw_metadata["title_zh"] = str(zh["title"])
            raw_metadata["raw_announcement_zh"] = dict(zh)
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
