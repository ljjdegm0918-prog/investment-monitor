"""Yellowbrick Investing community connector (registered stub; no live scrape)."""

from __future__ import annotations

import logging
from typing import List, Tuple

from ...models import MARKET_US, CollectionRequest, InformationItem

LOGGER = logging.getLogger(__name__)

# Documented public surface candidates for Yellowbrick Investing (all failed
# 2026-08-11 spike with stdlib urllib, no cookie, no WAF/login bypass).
LANDING_URL = "https://joinyellowbrick.com"
DEAD_DOMAIN = "https://ybrick.co"


def normalize_us_ticker(ticker: str) -> str:
    """Normalize a US equity symbol to its uppercase root form."""
    return str(ticker).strip().upper()


class YellowbrickConnector:
    """US community source for Yellowbrick Investing public pitches/ideas.

    ``status="stub"``: ``collect()`` does not hit the network and returns
    ``[]``. The Yellowbrick Investing product has no stable public,
    login-free surface suitable for automated collection: ``ybrick.co`` is
    dead, ``joinyellowbrick.com`` is a marketing landing page with all
    content paths returning 404, and the Substack is waitlist-only.
    """

    name = "yellowbrick"
    provider = "Yellowbrick Investing"
    status = "stub"

    def __init__(self) -> None:
        self._last_errors: Tuple[Tuple[str, str], ...] = ()

    @property
    def last_errors(self) -> Tuple[Tuple[str, str], ...]:
        return self._last_errors

    def collect(self, request: CollectionRequest) -> List[InformationItem]:
        """Honest stub: no live Yellowbrick Investing fetch.

        Records an honest error note per US ticker explaining the public
        surface failures found during the 2026-08-11 spike.
        """
        notes: List[Tuple[str, str]] = []
        for ticker in request.tickers:
            market = request.market_for(ticker)
            if market != MARKET_US:
                LOGGER.info(
                    "yellowbrick ticker=%s market=%s skipped not_us_market",
                    ticker,
                    market,
                )
                continue
            code = normalize_us_ticker(ticker)
            notes.append(
                (
                    code,
                    (
                        "yellowbrick stub: Yellowbrick Investing has no "
                        "stable public login-free surface (spike 2026-08-11): "
                        f"{DEAD_DOMAIN} is dead (DNS/transport error); "
                        f"{LANDING_URL}/stocks, /ideas, /pitches all return "
                        "HTTP 404; the Substack is waitlist-only. "
                        "yellowbrick.com/feed is LIVE RSS but belongs to the "
                        "SQL data platform vendor (wrong entity, out of "
                        "scope); login/Supabase-key scraping is out of scope"
                    ),
                )
            )
            LOGGER.info(
                "yellowbrick ticker=%s status=stub empty",
                code,
            )
        self._last_errors = tuple(notes)
        return []
