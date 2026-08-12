"""Substack (US) — LIVE publication-whitelist article/news metadata.

Substack is an author newsletter platform, **NOT** a ticker forum. There is
no public ticker search API, no ticker tag system, and no per-ticker
community surface (spike 2026-08-11, see tests/fixtures/substack/SPIKE.md).

This connector polls a **whitelist** of active Substack newsletters via their
public RSS feeds (``/feed``), filters by America/New_York calendar day, and
optionally matches ticker keywords client-side (best-effort, with
false-positive/negative caveats). Category is newsletter **article/news
metadata**, NOT forum/discussion posts.

No structured ticker binding: coverage depends on whitelist quality and
keyword match quality. Whitelist requires maintenance against off-platform
publication migration (e.g., thediff migrated to thediff.co).
"""

from .connector import SubstackConnector, SubstackRequestError
from .parser import SubstackFeedRow, new_york_day, parse_substack_rss

__all__ = [
    "SubstackConnector",
    "SubstackRequestError",
    "SubstackFeedRow",
    "new_york_day",
    "parse_substack_rss",
]
