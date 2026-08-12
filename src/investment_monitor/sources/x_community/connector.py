"""X (Twitter) community connector (registered stub; no live scrape)."""

from __future__ import annotations

import logging
from typing import List, Tuple

from ...models import MARKET_US, CollectionRequest, InformationItem

LOGGER = logging.getLogger(__name__)

# Documented public surface candidates for X (formerly Twitter) community
# content (all failed the 2026-08-11 spike with stdlib urllib, no cookie,
# no WAF/login bypass).
SEARCH_URL = "https://x.com/search?q=%24TICKER&f=live"
COMMUNITIES_URL = "https://x.com/i/communities"


def normalize_us_ticker(ticker: str) -> str:
    """Normalize a US equity symbol to its uppercase root form."""
    return str(ticker).strip().upper()


class XCommunityConnector:
    """US community source for X (Twitter) public posts / communities.

    ``status="stub"``: ``collect()`` does not hit the network and returns
    ``[]``. X has no stable public, login-free surface suitable for automated
    collection: search, Communities, and profile timelines are client-rendered
    SPA shells behind a login wall for urllib; every Nitter mirror is dead or
    bot-walled; the only key-free endpoints that return real content (single
    status page SSR, oEmbed, undocumented syndication ``tweet-result``) require
    a known tweet id/URL in advance and cannot enumerate or search by ticker.

    Unlock note (future optional LIVE): if a user-provided official X API key
    is supplied via ``X_BEARER_TOKEN``, the ``GET /2/tweets/search/recent``
    endpoint (Bearer/OAuth2, pay-per-usage credits ~$0.005/Post read) supports
    cashtag queries (``$TICKER``), ``start_time``/``end_time`` within a 7-day
    window, and returns stable ``id`` / ``created_at`` / ``text`` /
    ``community_id``. This commit is stub only — no key path is wired.
    """

    name = "x_community"
    provider = "X"
    status = "stub"

    def __init__(self) -> None:
        self._last_errors: Tuple[Tuple[str, str], ...] = ()

    @property
    def last_errors(self) -> Tuple[Tuple[str, str], ...]:
        return self._last_errors

    def collect(self, request: CollectionRequest) -> List[InformationItem]:
        """Honest stub: no live X fetch (login-walled SPA / key required).

        Records an honest error note per US ticker explaining the public
        surface failures found during the 2026-08-11 spike.
        """
        notes: List[Tuple[str, str]] = []
        for ticker in request.tickers:
            market = request.market_for(ticker)
            if market != MARKET_US:
                LOGGER.info(
                    "x_community ticker=%s market=%s skipped not_us_market",
                    ticker,
                    market,
                )
                continue
            code = normalize_us_ticker(ticker)
            notes.append(
                (
                    code,
                    (
                        "x_community stub: X has no stable public login-free "
                        "surface for ticker discovery (spike 2026-08-11): "
                        f"{SEARCH_URL} and {COMMUNITIES_URL} are client-"
                        "rendered SPA shells behind a login wall (no SSR for "
                        "urllib); every Nitter mirror is dead or bot-walled; "
                        "the only key-free endpoints that return real content "
                        "(single status page SSR, oEmbed, undocumented "
                        "syndication tweet-result) require a known tweet id/URL "
                        "in advance and cannot enumerate or search by ticker; "
                        "the official X API v2 search/recent endpoint requires "
                        "a paid Bearer/OAuth2 key (pay-per-usage credits) — "
                        "no-key/HTML-bypass/unofficial-scrape paths are out "
                        "of scope"
                    ),
                )
            )
            LOGGER.info(
                "x_community ticker=%s status=stub empty",
                code,
            )
        self._last_errors = tuple(notes)
        return []
