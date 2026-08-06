"""KIND (KRX) disclosure connector for market=kr companies."""

from __future__ import annotations

import logging
from datetime import date, datetime, time, timezone
from typing import Any, List, Mapping, Optional, Tuple
from zoneinfo import ZoneInfo

from ...models import CollectionRequest, InformationItem, MARKET_KR
from .client import (
    KindClient,
    KindRequestError,
    VIEWER_PATH,
)

LOGGER = logging.getLogger(__name__)

MAX_LOOKBACK_DAYS = 30
KST = ZoneInfo("Asia/Seoul")


class KindConnector:
    """Collect KIND exchange disclosures for active KR companies."""

    name = "kind"
    provider = "KIND (KRX)"
    max_lookback_days = MAX_LOOKBACK_DAYS
    # KIND is key-free; no secret_fields and no configuration_error.

    def __init__(self, client: Optional[KindClient] = None) -> None:
        self._client = client or KindClient.from_environment()
        self._last_errors: Tuple[Tuple[str, str], ...] = ()

    @property
    def last_errors(self) -> Tuple[Tuple[str, str], ...]:
        """(ticker, message) pairs from the most recent collect call."""
        return self._last_errors

    def collect(self, request: CollectionRequest) -> List[InformationItem]:
        """Collect disclosures per ticker; non-KR tickers skip silently."""
        items: List[InformationItem] = []
        failures: List[Tuple[str, str]] = []
        collected_at = datetime.now(timezone.utc)

        for ticker in request.tickers:
            market = request.market_for(ticker)
            if market != MARKET_KR:
                LOGGER.info(
                    "kind ticker=%s market=%s skipped not_kr_market",
                    ticker,
                    market,
                )
                continue
            normalized = _normalize_kr_ticker(ticker)
            try:
                records = self._client.search_disclosures(
                    normalized,
                    request.start_date,
                    request.end_date,
                )
                items.extend(
                    self._map_records(
                        records,
                        ticker=normalized,
                        start_date=request.start_date,
                        end_date=request.end_date,
                        collected_at=collected_at,
                    )
                )
            except Exception as error:
                message = str(error) or error.__class__.__name__
                failures.append((ticker, message))
                LOGGER.warning(
                    "kind ticker=%s status=failure error=%s",
                    ticker,
                    message,
                )

        self._last_errors = tuple(failures)
        if len(request.tickers) == 1 and failures:
            raise KindRequestError(failures[0][1])
        return items

    def _map_records(
        self,
        records: List[Mapping[str, Any]],
        *,
        ticker: str,
        start_date: date,
        end_date: date,
        collected_at: datetime,
    ) -> List[InformationItem]:
        items: List[InformationItem] = []
        for record in records:
            acpt_no = str(record.get("acpt_no") or "").strip()
            title = str(record.get("title") or "").strip()
            if not acpt_no or not title:
                continue
            company_name = str(record.get("company_name") or "").strip()
            datetime_text = str(record.get("datetime_text") or "").strip()
            published_at = _parse_kind_datetime(datetime_text)
            kst_day = _kind_date(datetime_text)
            if published_at is None or kst_day is None:
                continue
            if not start_date <= kst_day <= end_date:
                continue
            items.append(
                InformationItem(
                    source=self.name,
                    source_type="regulatory_filing",
                    external_id=acpt_no,
                    tickers=(ticker,),
                    issuer=company_name or ticker,
                    published_at=published_at,
                    title=title,
                    document_type="kind_disclosure",
                    url=self._client.viewer_url(acpt_no),
                    collected_at=collected_at,
                    raw_metadata={
                        "provider": "kind",
                        "stock_code": ticker,
                        "acpt_no": acpt_no,
                        "rcept_no": acpt_no,
                        "company_name": company_name,
                        "market": str(record.get("market") or ""),
                        "submitter": str(record.get("submitter") or ""),
                        "datetime_text": str(
                            record.get("datetime_text") or ""
                        ),
                    },
                    market=MARKET_KR,
                    summary=None,
                    effective_at=published_at,
                )
            )
        return items


def _normalize_kr_ticker(ticker: str) -> str:
    """Normalize a KR stock code to six digits (5930 -> 005930)."""
    raw = ticker.strip()
    return raw.zfill(6) if raw.isdigit() else raw


def _parse_kind_datetime(value: str) -> Optional[datetime]:
    """Parse a KIND 'YYYY-MM-DD HH:MM' KST cell into UTC."""
    try:
        parsed = datetime.strptime(value, "%Y-%m-%d %H:%M")
    except ValueError:
        return None
    kst_aware = parsed.replace(tzinfo=KST)
    return kst_aware.astimezone(timezone.utc)


def _kind_date(value: str) -> Optional[date]:
    try:
        return datetime.strptime(value[:10], "%Y-%m-%d").date()
    except ValueError:
        return None
