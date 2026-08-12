"""HotCopper AU community connector (registered stub; no live scrape)."""

from __future__ import annotations

import logging
from datetime import date, datetime, timezone
from typing import List, Mapping, Optional, Sequence, Tuple
from zoneinfo import ZoneInfo

from ...models import MARKET_AU, CollectionRequest, InformationItem
from ...web_repository import normalize_au_ticker
from .parser import HotCopperThreadRow, parse_hotcopper_thread_list

LOGGER = logging.getLogger(__name__)
SYDNEY = ZoneInfo("Australia/Sydney")

# Documented public board URL pattern (blocked by Cloudflare for bots, 2026-08-11).
BOARD_URL_TEMPLATE = "https://hotcopper.com.au/asx/{ticker}/"


class HotCopperAuConnector:
    """AU community source for HotCopper public posts.

    ``status="stub"``: ``collect()`` does not hit the network and returns ``[]``.
    Parser helpers remain unit-tested against fixtures for a future unlock.
    """

    name = "hotcopper_au"
    provider = "HotCopper"
    status = "stub"

    def __init__(self) -> None:
        self._last_errors: Tuple[Tuple[str, str], ...] = ()

    @property
    def last_errors(self) -> Tuple[Tuple[str, str], ...]:
        return self._last_errors

    def collect(self, request: CollectionRequest) -> List[InformationItem]:
        """Honest stub: no live HotCopper fetch (Cloudflare 403 on public pages)."""
        notes: List[Tuple[str, str]] = []
        for ticker in request.tickers:
            market = request.market_for(ticker)
            if market != MARKET_AU:
                continue
            code = normalize_au_ticker(ticker)
            notes.append(
                (
                    code,
                    (
                        "hotcopper_au stub: public board "
                        f"{BOARD_URL_TEMPLATE.format(ticker=code.lower())} "
                        "returns HTTP 403 Cloudflare challenge to automated "
                        "clients (spike 2026-08-11); login/paywall content "
                        "is out of scope"
                    ),
                )
            )
            LOGGER.info(
                "hotcopper_au ticker=%s status=stub empty",
                code,
            )
        self._last_errors = tuple(notes)
        return []

    def map_rows_for_tests(
        self,
        rows: Sequence[HotCopperThreadRow],
        *,
        ticker: str,
        collected_at: Optional[datetime] = None,
    ) -> List[InformationItem]:
        """Map parsed rows to InformationItems (unit tests / future live path)."""
        code = normalize_au_ticker(ticker)
        collected = collected_at or datetime.now(timezone.utc)
        items: List[InformationItem] = []
        for row in rows:
            summary = (row.summary or "")[:500] or None
            items.append(
                InformationItem(
                    source=self.name,
                    source_type="community",
                    external_id=f"hotcopper-{row.thread_id}",
                    tickers=(code,),
                    issuer=code,
                    published_at=row.published_at.astimezone(timezone.utc),
                    title=row.title,
                    document_type="community_post",
                    url=row.url,
                    collected_at=collected,
                    raw_metadata={
                        "provider": "hotcopper",
                        "thread_id": row.thread_id,
                        "stock_code": code,
                        "board_url": BOARD_URL_TEMPLATE.format(
                            ticker=code.lower()
                        ),
                        "stub": True,
                    },
                    market=MARKET_AU,
                    summary=summary,
                    effective_at=row.published_at.astimezone(timezone.utc),
                )
            )
        return items


def sydney_day(moment: datetime) -> date:
    """Calendar day in Australia/Sydney for day filtering."""
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment.astimezone(SYDNEY).date()


def parse_board_html_for_day(
    html: str,
    *,
    on_date: date,
) -> List[HotCopperThreadRow]:
    """Public helper used by unit tests (same as parser entrypoint)."""
    return parse_hotcopper_thread_list(html, on_date=on_date)
