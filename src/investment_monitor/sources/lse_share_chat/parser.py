"""Parse public LSE Share Chat thread-list HTML (fixture / future live page).

Synthetic fixture mirrors a documented public board URL pattern
``/ShareChat/{ticker}/`` with thread links and Europe/London timestamps.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime
from typing import List, Optional
from zoneinfo import ZoneInfo

LONDON = ZoneInfo("Europe/London")

# Example: /ShareChat/thread/bp-results-chat.9022606/
_THREAD_HREF = re.compile(
    r'href="(?P<url>https?://(?:www\.)?lse\.co\.uk/ShareChat/thread/'
    r'(?P<slug>[^\"/?#]+)\.(?P<thread_id>\d+)/?)"',
    re.IGNORECASE,
)
_TITLE_IN_ANCHOR = re.compile(
    r'href="https?://(?:www\.)?lse\.co\.uk/ShareChat/thread/'
    r'[^\"/?#]+\.\d+/?">\s*(?P<title>[^<]+?)\s*</a>',
    re.IGNORECASE,
)
_DATETIME_ATTR = re.compile(
    r'(?:data-posted|datetime)="(?P<ts>[^"]+)"',
    re.IGNORECASE,
)


@dataclass(frozen=True)
class LseShareChatThreadRow:
    """One publicly listed LSE Share Chat thread row."""

    thread_id: str
    title: str
    url: str
    published_at: datetime
    summary: Optional[str] = None


def parse_lse_share_chat_thread_list(
    html: str,
    *,
    on_date: date,
) -> List[LseShareChatThreadRow]:
    """Return thread rows whose London calendar day equals ``on_date``.

    Rows missing a parseable timestamp or title/url are skipped.
    """
    rows: List[LseShareChatThreadRow] = []
    for match in _THREAD_HREF.finditer(html):
        thread_id = match.group("thread_id")
        url = match.group("url")
        if not url.endswith("/"):
            url = url + "/"
        after = html[match.end() : min(len(html), match.end() + 800)]
        before = html[max(0, match.start() - 200) : match.start()]
        window = before + html[match.start() : match.end()] + after
        title_match = _TITLE_IN_ANCHOR.search(window)
        title = (title_match.group("title") if title_match else "").strip()
        if not title:
            slug = match.group("slug").replace("-", " ").strip()
            title = slug[:200] if slug else f"LSE Share Chat thread {thread_id}"
        ts_match = _DATETIME_ATTR.search(after) or _DATETIME_ATTR.search(before)
        if not ts_match:
            continue
        published = _parse_timestamp(ts_match.group("ts"))
        if published is None:
            continue
        if published.astimezone(LONDON).date() != on_date:
            continue
        rows.append(
            LseShareChatThreadRow(
                thread_id=thread_id,
                title=title[:500],
                url=url,
                published_at=published,
                summary=None,
            )
        )
    seen: set[str] = set()
    unique: List[LseShareChatThreadRow] = []
    for row in rows:
        if row.thread_id in seen:
            continue
        seen.add(row.thread_id)
        unique.append(row)
    return unique


def _parse_timestamp(raw: str) -> Optional[datetime]:
    text = str(raw or "").strip().replace("Z", "+00:00")
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=LONDON)
    return parsed
