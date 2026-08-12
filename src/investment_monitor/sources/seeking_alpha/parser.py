"""Parse Seeking Alpha public combined RSS (news + analysis metadata).

Spike 2026-08-11: ``https://seekingalpha.com/api/sa/combined/{SYMBOL}.xml``
returns RSS 2.0 with ``MarketCurrent`` / ``Article`` items. This is an
article/news stream, not forum comments.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime, timezone
from email.utils import parsedate_to_datetime
from typing import List, Optional
from xml.etree import ElementTree as ET
from zoneinfo import ZoneInfo

NEW_YORK = ZoneInfo("America/New_York")
MAX_SUMMARY_LEN = 500
SA_NS = {"sa": "https://seekingalpha.com/api/1.0"}
_GUID_ID = re.compile(
    r"(?:MarketCurrent|Article):(?P<id>\d+)",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class SeekingAlphaFeedRow:
    """One RSS item from the Seeking Alpha combined symbol feed."""

    content_id: str
    content_kind: str
    title: str
    url: str
    published_at: datetime
    summary: Optional[str] = None


def new_york_day(moment: datetime) -> date:
    """Calendar day in America/New_York."""
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment.astimezone(NEW_YORK).date()


def parse_seeking_alpha_combined_rss(
    xml_text: str,
    *,
    on_date: date,
) -> List[SeekingAlphaFeedRow]:
    """Return feed rows whose New York calendar day equals ``on_date``."""
    root = ET.fromstring(xml_text)
    rows: List[SeekingAlphaFeedRow] = []
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
        content_id, kind = _split_guid(guid)
        if not content_id:
            continue
        desc = (item.findtext("description") or "").strip() or None
        if desc:
            desc = desc[:MAX_SUMMARY_LEN]
        rows.append(
            SeekingAlphaFeedRow(
                content_id=content_id,
                content_kind=kind,
                title=title[:500],
                url=link,
                published_at=published,
                summary=desc,
            )
        )
    seen: set[str] = set()
    unique: List[SeekingAlphaFeedRow] = []
    for row in rows:
        key = f"{row.content_kind}:{row.content_id}"
        if key in seen:
            continue
        seen.add(key)
        unique.append(row)
    return unique


def _split_guid(guid: str) -> tuple[str, str]:
    match = _GUID_ID.search(guid)
    if not match:
        return "", "unknown"
    kind = "article" if "Article" in match.group(0) else "market_current"
    if match.group(0).lower().startswith("article"):
        kind = "article"
    elif match.group(0).lower().startswith("marketcurrent"):
        kind = "market_current"
    return match.group("id"), kind


def _parse_pub_date(raw: str) -> Optional[datetime]:
    try:
        parsed = parsedate_to_datetime(raw)
    except (TypeError, ValueError, IndexError):
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=NEW_YORK)
    return parsed
