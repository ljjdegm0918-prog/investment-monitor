"""Value Investors Club (VIC) US community connector — honest stub after spike.

Live public collection is **not** wired: valueinvestorsclub.com has no public
RSS/JSON API (``/feed``, ``/rss``, ``/api/ideas``, ``sitemap.xml`` return HTML
shells); ``/ideas?symbol=TICKER`` does not filter (identical idea-href set for
MSFT/AAPL/bare ``/ideas``); recent ideas require membership or a free signup
that only unlocks **45-day delayed** guest access (homepage copy, spike
2026-08-11). Individual historical idea pages are readable without login, but
there is no stable key-free ticker + calendar-day discovery path. Membership /
login / HTML catalog scrape out of scope. ``collect()`` returns an empty list.
"""

from .connector import VicConnector

__all__ = [
    "VicConnector",
]
