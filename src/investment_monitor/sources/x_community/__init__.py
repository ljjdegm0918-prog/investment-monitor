"""X (Twitter) US community connector — official API path only.

There is still no compliant key-free discovery surface: X search,
Communities, and profile timelines are client-rendered SPA shells behind a
login wall for urllib; every Nitter mirror is dead or bot-walled; the only
key-free endpoints that return real content (single status page SSR, oEmbed,
undocumented syndication ``tweet-result``) require a known tweet id/URL in
advance and cannot enumerate or search by ticker.

The supported live path is the official X API v2
``GET /2/tweets/search/recent`` with a user-provided ``X_BEARER_TOKEN``.
Without that token the connector stays unavailable instead of scraping HTML or
using undocumented syndication endpoints.
"""

from .connector import XCommunityConnector

__all__ = [
    "XCommunityConnector",
]
