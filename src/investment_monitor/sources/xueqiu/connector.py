"""Xueqiu (雪球) CN/HK community connector (registered stub; no live scrape)."""

from __future__ import annotations

import logging
from datetime import date, datetime, timezone
from typing import List, Optional, Sequence, Tuple
from zoneinfo import ZoneInfo

from ...models import (
    MARKET_CN,
    MARKET_HK,
    CollectionRequest,
    InformationItem,
)
from ...web_repository import normalize_cn_ticker, normalize_xq_symbol
from .parser import (
    HONG_KONG,
    SHANGHAI,
    XueqiuPostRow,
    parse_xueqiu_status_list,
)

LOGGER = logging.getLogger(__name__)

# Documented public symbol page URL pattern (Aliyun WAF JS-challenge to
# automated clients; JSON APIs require xq_a_token, 2026-08-11).
SYMBOL_URL_TEMPLATE = "https://xueqiu.com/S/{symbol}"


class XueqiuConnector:
    """CN/HK community source for Xueqiu public statuses.

    ``status="stub"``: ``collect()`` does not hit the network and returns
    ``[]``. Parser helpers remain unit-tested against fixtures for a future
    unlock.
    """

    name = "xueqiu"
    provider = "Xueqiu"
    status = "stub"

    def __init__(self) -> None:
        self._last_errors: Tuple[Tuple[str, str], ...] = ()

    @property
    def last_errors(self) -> Tuple[Tuple[str, str], ...]:
        return self._last_errors

    def collect(self, request: CollectionRequest) -> List[InformationItem]:
        """Honest stub: no live Xueqiu fetch (WAF challenge / token required)."""
        notes: List[Tuple[str, str]] = []
        for ticker in request.tickers:
            market = request.market_for(ticker)
            if market not in (MARKET_CN, MARKET_HK):
                LOGGER.info(
                    "xueqiu ticker=%s market=%s skipped not_cn_hk",
                    ticker,
                    market,
                )
                continue
            code = normalize_xq_symbol(ticker, market=market)
            notes.append(
                (
                    code,
                    (
                        "xueqiu stub: public symbol page "
                        f"{SYMBOL_URL_TEMPLATE.format(symbol=code)} is an "
                        "Aliyun WAF JS-challenge shell and the JSON APIs "
                        "require a valid xq_a_token session cookie (error "
                        "400016) (spike 2026-08-11); login/WAF bypass "
                        "content is out of scope"
                    ),
                )
            )
            LOGGER.info(
                "xueqiu ticker=%s symbol=%s status=stub empty",
                ticker,
                code,
            )
        self._last_errors = tuple(notes)
        return []

    def map_rows_for_tests(
        self,
        rows: Sequence[XueqiuPostRow],
        *,
        ticker: str,
        market: str,
        collected_at: Optional[datetime] = None,
    ) -> List[InformationItem]:
        """Map parsed rows to InformationItems (unit tests / future live path)."""
        code = normalize_xq_symbol(ticker, market=market)
        collected = collected_at or datetime.now(timezone.utc)
        items: List[InformationItem] = []
        for row in rows:
            summary = (row.summary or "")[:500] or None
            items.append(
                InformationItem(
                    source=self.name,
                    source_type="community",
                    external_id=f"xueqiu-{row.status_id}",
                    tickers=(code,),
                    issuer=code,
                    published_at=row.published_at.astimezone(timezone.utc),
                    title=row.title,
                    document_type="community_post",
                    url=row.url,
                    collected_at=collected,
                    raw_metadata={
                        "provider": "xueqiu",
                        "status_id": row.status_id,
                        "stock_code": code,
                        "symbol_url": SYMBOL_URL_TEMPLATE.format(
                            symbol=code
                        ),
                        "stub": True,
                    },
                    market=market,
                    summary=summary,
                    effective_at=row.published_at.astimezone(timezone.utc),
                )
            )
        return items


def local_day(moment: datetime, market: str) -> date:
    """Calendar day in the market's local zone for day filtering."""
    zone = SHANGHAI if market == MARKET_CN else HONG_KONG
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment.astimezone(zone).date()


def parse_board_html_for_day(
    html: str,
    *,
    on_date: date,
    market: str,
) -> List[XueqiuPostRow]:
    """Public helper used by unit tests (same as parser entrypoint)."""
    return parse_xueqiu_status_list(html, on_date=on_date, market=market)
