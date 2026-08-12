"""LSE Share Chat UK community connector (registered stub; no live scrape)."""

from __future__ import annotations

import logging
from datetime import date, datetime, timezone
from typing import List, Optional, Sequence, Tuple
from zoneinfo import ZoneInfo

from ...models import MARKET_UK, CollectionRequest, InformationItem
from ...web_repository import normalize_uk_ticker
from .parser import LseShareChatThreadRow, parse_lse_share_chat_thread_list

LOGGER = logging.getLogger(__name__)
LONDON = ZoneInfo("Europe/London")

# Documented public board URL pattern (HTTP 403 to automated clients, 2026-08-11).
BOARD_URL_TEMPLATE = "https://www.lse.co.uk/ShareChat/{ticker}/"


class LseShareChatConnector:
    """UK community source for LSE.co.uk Share Chat public posts.

    ``status="stub"``: ``collect()`` does not hit the network and returns ``[]``.
    Parser helpers remain unit-tested against fixtures for a future unlock.
    """

    name = "lse_share_chat"
    provider = "LSE Share Chat"
    status = "stub"

    def __init__(self) -> None:
        self._last_errors: Tuple[Tuple[str, str], ...] = ()

    @property
    def last_errors(self) -> Tuple[Tuple[str, str], ...]:
        return self._last_errors

    def collect(self, request: CollectionRequest) -> List[InformationItem]:
        """Honest stub: no live LSE Share Chat fetch (403 / SPA shell)."""
        notes: List[Tuple[str, str]] = []
        for ticker in request.tickers:
            market = request.market_for(ticker)
            if market != MARKET_UK:
                continue
            code = normalize_uk_ticker(ticker)
            board = BOARD_URL_TEMPLATE.format(ticker=code.lower())
            notes.append(
                (
                    code,
                    (
                        "lse_share_chat stub: public board "
                        f"{board} returns HTTP 403 to automated clients; "
                        "londonstockexchange.com discussion URLs are SPA "
                        "shells without server-rendered posts "
                        "(spike 2026-08-11); login/paywall content is "
                        "out of scope"
                    ),
                )
            )
            LOGGER.info(
                "lse_share_chat ticker=%s status=stub empty",
                code,
            )
        self._last_errors = tuple(notes)
        return []

    def map_rows_for_tests(
        self,
        rows: Sequence[LseShareChatThreadRow],
        *,
        ticker: str,
        collected_at: Optional[datetime] = None,
    ) -> List[InformationItem]:
        """Map parsed rows to InformationItems (unit tests / future live path)."""
        code = normalize_uk_ticker(ticker)
        collected = collected_at or datetime.now(timezone.utc)
        items: List[InformationItem] = []
        for row in rows:
            summary = (row.summary or "")[:500] or None
            items.append(
                InformationItem(
                    source=self.name,
                    source_type="community",
                    external_id=f"lse-share-chat-{row.thread_id}",
                    tickers=(code,),
                    issuer=code,
                    published_at=row.published_at.astimezone(timezone.utc),
                    title=row.title,
                    document_type="community_post",
                    url=row.url,
                    collected_at=collected,
                    raw_metadata={
                        "provider": "lse_share_chat",
                        "thread_id": row.thread_id,
                        "stock_code": code,
                        "board_url": BOARD_URL_TEMPLATE.format(
                            ticker=code.lower()
                        ),
                        "stub": True,
                    },
                    market=MARKET_UK,
                    summary=summary,
                    effective_at=row.published_at.astimezone(timezone.utc),
                )
            )
        return items


def london_day(moment: datetime) -> date:
    """Calendar day in Europe/London for day filtering."""
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment.astimezone(LONDON).date()


def parse_board_html_for_day(
    html: str,
    *,
    on_date: date,
) -> List[LseShareChatThreadRow]:
    """Public helper used by unit tests (same as parser entrypoint)."""
    return parse_lse_share_chat_thread_list(html, on_date=on_date)
