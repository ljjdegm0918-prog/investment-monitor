"""Parse Substack public RSS feeds (author newsletter article/news stream).

Spike 2026-08-11: Substack ``/feed`` returns RSS 2.0 with stable ``guid``
(canonical article URL), ``title``, ``link``, ``pubDate`` (RFC 2822 GMT),
and optional ``description``. The feed is login-free on active publications.
Substack is NOT a ticker forum — no per-ticker filtering exists.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timezone
from email.utils import parsedate_to_datetime
from typing import List, Optional
from xml.etree import ElementTree as ET
from zoneinfo import ZoneInfo

NEW_YORK = ZoneInfo("America/New_York")
MAX_SUMMARY_LEN = 500


@dataclass(frozen=True)
class SubstackFeedRow:
    """One RSS item from a Substack publication feed."""

    post_id: str
    title: str
    url: str
    published_at: datetime
    summary: Optional[str] = None


def new_york_day(moment: datetime) -> date:
    """Calendar day in America/New_York."""
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment.astimezone(NEW_YORK).date()


def parse_substack_rss(
    rss_text: str,
    *,
    on_date: date,
) -> List[SubstackFeedRow]:
    """Return RSS items whose New York calendar day equals ``on_date``."""
    root = ET.fromstring(rss_text)
    rows: List[SubstackFeedRow] = []
    for item in root.findall("./channel/item"):
        title = (item.findtext("title") or "").strip()
        link = (item.findtext("link") or "").strip()
        guid = (item.findtext("guid") or "").strip()
        pub_raw = (item.findtext("pubDate") or "").strip()
        if not title or not link or not guid or not pub_raw:
            continue
        published = _parse_pub_date(pub_raw)
        if published is None:
            continue
        if new_york_day(published) != on_date:
            continue
        desc = (item.findtext("description") or "").strip() or None
        if desc:
            desc = desc[:MAX_SUMMARY_LEN]
        rows.append(
            SubstackFeedRow(
                post_id=guid,
                title=title[:500],
                url=link,
                published_at=published,
                summary=desc,
            )
        )
    return rows


def _parse_pub_date(raw: str) -> Optional[datetime]:
    try:
        parsed = parsedate_to_datetime(raw)
    except (TypeError, ValueError, IndexError):
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed
