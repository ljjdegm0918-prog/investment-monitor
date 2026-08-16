# -*- coding: utf-8 -*-
"""Nasdaq Baltic issuer announcements connector for market in {ee, lv, lt}.

Only issuer announcements are collected (``company`` is the issuer name);
exchange notices (``company`` starts with ``Nasdaq ``) are intentionally
skipped because they are not bound to a single ticker. Items are matched to
universe companies by exact normalized issuer name. Date windows are
enforced against the official published timestamp, expressed in the
Europe/Tallinn zone used by the official site.
"""

from __future__ import annotations

import logging
from datetime import date, datetime, timedelta, timezone
from typing import Any, Callable, List, Mapping, Optional, Tuple

from ...models import (
    CollectionRequest,
    InformationItem,
    MARKET_EE,
    MARKET_LV,
    MARKET_LT,
)
from ...web_repository import (
    normalize_ee_ticker,
    normalize_lt_ticker,
    normalize_lv_ticker,
)
from .client import BalticNewsClient, BalticNewsRequestError
from .matcher import BalticCompanyMatcher

LOGGER = logging.getLogger(__name__)

BALTIC_MARKETS = frozenset({MARKET_EE, MARKET_LV, MARKET_LT})
EXCHANGE_COMPANY_PREFIX = "NASDAQ "
MAX_LOOKBACK_DAYS = 30
BALTIC_ZONE = "Europe/Tallinn"

_NORMALIZERS = {
    MARKET_EE: normalize_ee_ticker,
    MARKET_LV: normalize_lv_ticker,
    MARKET_LT: normalize_lt_ticker,
}


class NasdaqBalticNewsConnector:
    """Collect official Nasdaq Baltic issuer announcements."""

    name = "nasdaq_baltic_news"
    provider = "Nasdaq Baltic"
    max_lookback_days = MAX_LOOKBACK_DAYS

    def __init__(
        self,
        client: Optional[BalticNewsClient] = None,
        matcher: Optional[BalticCompanyMatcher] = None,
    ) -> None:
        self._client = client or BalticNewsClient.from_environment()
        self._matcher = matcher or BalticCompanyMatcher()
        self._last_errors: Tuple[Tuple[str, str], ...] = ()

    @property
    def last_errors(self) -> Tuple[Tuple[str, str], ...]:
        return self._last_errors

    def collect(self, request: CollectionRequest) -> List[InformationItem]:
        items: List[InformationItem] = []
        failures: List[Tuple[str, str]] = []
        collected_at = datetime.now(timezone.utc)
        market_groups: dict[str, List[str]] = {}
        for ticker in request.tickers:
            market = request.market_for(ticker)
            if market not in BALTIC_MARKETS:
                LOGGER.info(
                    "nasdaq_baltic_news ticker=%s market=%s skipped not_baltic_market",
                    ticker,
                    market,
                )
                continue
            normalizer = _NORMALIZERS[market]
            market_groups.setdefault(market, []).append(normalizer(ticker))
        for market, tickers in market_groups.items():
            try:
                self._matcher.load_universe(market)
                for day in _days_between(request.start_date, request.end_date):
                    for record in self._client.fetch_market_day(day, market):
                        item = self._to_item(
                            record, market, tuple(tickers), collected_at
                        )
                        if item is not None:
                            items.append(item)
            except Exception as error:  # noqa: BLE001 - connector 统一收编失败
                message = str(error) or error.__class__.__name__
                failures.append((" ".join(tickers), message))
                LOGGER.warning(
                    "nasdaq_baltic_news market=%s status=failure error=%s",
                    market,
                    message,
                )
        self._last_errors = tuple(failures)
        if len(request.tickers) == 1 and failures:
            raise BalticNewsRequestError(failures[0][1])
        return items

    def _to_item(
        self,
        record: Mapping[str, Any],
        market: str,
        tickers: Tuple[str, ...],
        collected_at: datetime,
    ) -> Optional[InformationItem]:
        company = str(record.get("company") or "").strip()
        if not company or company.upper().startswith(EXCHANGE_COMPANY_PREFIX):
            return None
        published = _parse_published(record.get("published"))
        if published is None:
            return None
        ticker = self._matcher.match(company, tickers)
        if ticker is None:
            LOGGER.info(
                "nasdaq_baltic_news market=%s company=%r unmatched_skipped",
                market,
                company,
            )
            return None
        headline = str(record.get("headline") or "Nasdaq Baltic announcement").strip()
        url = str(record.get("messageUrl") or "")
        disclosure_id = record.get("disclosureId")
        return InformationItem(
            source=self.name,
            source_type="filings",
            external_id=f"baltic:{disclosure_id}",
            tickers=(ticker,),
            issuer=company,
            published_at=published,
            title=headline,
            document_type=str(record.get("cnsCategory") or "Company Announcement"),
            url=url if url.startswith(("http://", "https://")) else "",
            collected_at=collected_at,
            raw_metadata={
                "market": str(record.get("market") or ""),
                "language": str(record.get("language") or ""),
                "cns_type_id": str(record.get("cnsTypeId") or ""),
            },
            market=market,
        )


def _parse_published(value: Any) -> Optional[datetime]:
    if not value:
        return None
    text = str(value).strip()
    try:
        parsed = datetime.strptime(text, "%Y-%m-%d %H:%M:%S %z")
    except ValueError:
        try:
            parsed = datetime.strptime(text, "%Y-%m-%d %H:%M:%S")
        except ValueError:
            return None
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _days_between(start: date, end: date) -> List[date]:
    days: List[date] = []
    current = start
    while current <= end:
        days.append(current)
        current += timedelta(days=1)
    return days


__all__ = [
    "BalticNewsClient",
    "BalticNewsDataError",
    "BalticNewsError",
    "BalticNewsRequestError",
    "NasdaqBalticNewsConnector",
]
