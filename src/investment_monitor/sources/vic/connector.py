"""Value Investors Club connector (registered stub; no live scrape)."""

from __future__ import annotations

import logging
from typing import List, Tuple

from ...models import MARKET_US, CollectionRequest, InformationItem

LOGGER = logging.getLogger(__name__)

# Documented public surface candidates for VIC (all failed the 2026-08-11
# spike for key-free ticker+day collection with stdlib urllib, no cookie,
# no membership/login).
HOME_URL = "https://valueinvestorsclub.com/"
IDEAS_URL = "https://valueinvestorsclub.com/ideas"
FEED_URL = "https://valueinvestorsclub.com/feed"
RSS_URL = "https://valueinvestorsclub.com/rss"


def normalize_us_ticker(ticker: str) -> str:
    """Normalize a US equity symbol to its uppercase root form."""
    return str(ticker).strip().upper()


class VicConnector:
    """US community source for Value Investors Club investment ideas.

    ``status="stub"``: ``collect()`` does not hit the network and returns
    ``[]``. VIC is a members-first stock-idea club: guests may signup for
    **45-day delayed** ideas; there is no public RSS/JSON API; ``/ideas?
    symbol=TICKER`` does not filter by ticker (spike 2026-08-11). Historical
    idea HTML pages exist without login, but there is no stable key-free
    ticker + calendar-day discovery surface suitable for automated
    collection.

    Unlock note (future): only if the product accepts membership credentials
    or a vendor-provided export with stable id/time/ticker fields — not wired
    here; HTML membership-wall scrape remains out of scope.
    """

    name = "vic"
    provider = "Value Investors Club"
    status = "stub"

    def __init__(self) -> None:
        self._last_errors: Tuple[Tuple[str, str], ...] = ()

    @property
    def last_errors(self) -> Tuple[Tuple[str, str], ...]:
        return self._last_errors

    def collect(self, request: CollectionRequest) -> List[InformationItem]:
        """Honest stub: no live VIC fetch (membership / no public feed).

        Records an honest error note per US ticker explaining the public
        surface failures found during the 2026-08-11 spike.
        """
        notes: List[Tuple[str, str]] = []
        for ticker in request.tickers:
            market = request.market_for(ticker)
            if market != MARKET_US:
                LOGGER.info(
                    "vic ticker=%s market=%s skipped not_us_market",
                    ticker,
                    market,
                )
                continue
            code = normalize_us_ticker(ticker)
            notes.append(
                (
                    code,
                    (
                        "vic stub: Value Investors Club has no stable public "
                        "login-free ticker+day surface (spike 2026-08-11): "
                        f"{FEED_URL} and {RSS_URL} (and /api/ideas, "
                        "sitemap.xml) return HTML shells not RSS/JSON; "
                        f"{IDEAS_URL}?symbol=TICKER does not filter "
                        "(identical idea-href set for MSFT/AAPL/bare /ideas); "
                        f"{HOME_URL} offers free signup only for 45-day "
                        "delayed guest ideas; membership/login and HTML "
                        "catalog scrape are out of scope"
                    ),
                )
            )
            LOGGER.info(
                "vic ticker=%s status=stub empty",
                code,
            )
        self._last_errors = tuple(notes)
        return []
