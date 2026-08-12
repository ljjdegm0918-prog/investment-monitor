"""Seeking Alpha (US) — live public combined RSS (article/news stream).

HTML forum/comments are PerimeterX-blocked (spike 2026-08-11). The connector
reads ``/api/sa/combined/{SYMBOL}.xml`` only and documents the category as
article/news metadata, not discussion posts.
"""

from .connector import (
    SeekingAlphaConnector,
    SeekingAlphaRequestError,
    normalize_us_ticker,
)
from .parser import (
    SeekingAlphaFeedRow,
    new_york_day,
    parse_seeking_alpha_combined_rss,
)

__all__ = [
    "SeekingAlphaConnector",
    "SeekingAlphaRequestError",
    "SeekingAlphaFeedRow",
    "normalize_us_ticker",
    "new_york_day",
    "parse_seeking_alpha_combined_rss",
]
