# -*- coding: utf-8 -*-
"""NSE corporate announcements connector for market=in companies."""

from __future__ import annotations

import logging
from datetime import date, datetime, timedelta, timezone
from typing import Any, Callable, List, Mapping, Optional, Tuple

from ...models import CollectionRequest, InformationItem, MARKET_IN
from ...web_repository import normalize_in_ticker
from .client import NseAnnouncementsClient, NseAnnouncementsRequestError

LOGGER = logging.getLogger(__name__)

KOLKATA = timezone(timedelta(hours=5, minutes=30))
MAX_LOOKBACK_DAYS = 30


class NseAnnouncementsConnector:
    """Collect official NSE corporate announcements for market=in."""

    name = "nse_announcements"
    provider = "NSE"
    max_lookback_days = MAX_LOOKBACK_DAYS

    def __init__(
        self,
        client: Optional[NseAnnouncementsClient] = None,
    ) -> None:
        self._client = client or NseAnnouncementsClient.from_environment()
        self._last_errors: Tuple[Tuple[str, str], ...] = ()

    @property
    def last_errors(self) -> Tuple[Tuple[str, str], ...]:
        return self._last_errors

    def collect(self, request: CollectionRequest) -> List[InformationItem]:
        items: List[InformationItem] = []
        failures: List[Tuple[str, str]] = []
        collected_at = datetime.now(timezone.utc)
        requested_symbols = set()
        for ticker in request.tickers:
            market = request.market_for(ticker)
            if market != MARKET_IN:
                LOGGER.info(
                    "nse_announcements ticker=%s market=%s skipped not_in_market",
                    ticker,
                    market,
                )
                continue
            requested_symbols.add(normalize_in_ticker(ticker))
        if not requested_symbols:
            return items
        try:
            for day in _days_between(request.start_date, request.end_date):
                for record in self._client.fetch_day(day):
                    symbol = str(record.get("symbol") or "").strip().upper()
                    if symbol not in requested_symbols:
                        continue
                    item = self._to_item(record, collected_at)
                    if item is not None:
                        items.append(item)
        except Exception as error:  # noqa: BLE001 - connector 统一收编失败
            message = str(error) or error.__class__.__name__
            failures.append((" ".join(sorted(requested_symbols)), message))
            LOGGER.warning("nse_announcements status=failure error=%s", message)
        self._last_errors = tuple(failures)
        if len(request.tickers) == 1 and failures:
            raise NseAnnouncementsRequestError(failures[0][1])
        return items

    @staticmethod
    def _to_item(
        record: Mapping[str, Any],
        collected_at: datetime,
    ) -> Optional[InformationItem]:
        published = _parse_ist(record.get("an_dt"))
        if published is None:
            return None
        seq_id = record.get("seq_id")
        symbol = str(record.get("symbol") or "").strip().upper()
        headline = str(record.get("desc") or "Corporate announcement").strip()
        return InformationItem(
            source="nse_announcements",
            source_type="regulatory_filing",
            external_id=f"nse:{seq_id}",
            tickers=(symbol,),
            issuer=str(record.get("sm_name") or symbol),
            published_at=published,
            title=headline,
            document_type=headline,
            url=str(record.get("attchmntFile") or ""),
            collected_at=collected_at,
            raw_metadata={
                "isin": str(record.get("sm_isin") or ""),
                "summary": str(record.get("attchmntText") or ""),
                "industry": str(record.get("smIndustry") or ""),
            },
            market=MARKET_IN,
        )


def _parse_ist(value: Any) -> Optional[datetime]:
    if not value:
        return None
    try:
        parsed = datetime.strptime(str(value).strip(), "%d-%b-%Y %H:%M:%S")
    except ValueError:
        return None
    return parsed.replace(tzinfo=KOLKATA).astimezone(timezone.utc)


def _days_between(start: date, end: date) -> List[date]:
    days: List[date] = []
    current = start
    while current <= end:
        days.append(current)
        current += timedelta(days=1)
    return days


__all__ = [
    "NseAnnouncementsClient",
    "NseAnnouncementsConnector",
    "NseAnnouncementsDataError",
    "NseAnnouncementsError",
    "NseAnnouncementsRequestError",
]
