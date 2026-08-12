"""X (Twitter) US community connector — honest stub after spike.

Live public HTML/JSON collection is **not** wired: X search, Communities, and
profile timelines are client-rendered SPA shells behind a login wall for
urllib (no SSR), every Nitter mirror is dead or bot-walled, and the only
key-free endpoints that return real content (single status page SSR, oEmbed,
undocumented syndication ``tweet-result``) require a known tweet id/URL in
advance and cannot enumerate or search by ticker (spike 2026-08-11). The
official X API v2 ``GET /2/tweets/search/recent`` endpoint requires a paid
Bearer/OAuth2 key. Do not enable login-wall or undocumented-syndication
scraping. ``collect()`` returns an empty list until a stable public
login-free feed or a user-provided official API key exists.
"""

from .connector import XCommunityConnector

__all__ = [
    "XCommunityConnector",
]
