"""Parse public HotCopper thread-list HTML (fixture / future live page).

Expected list-row shape (synthetic fixture mirrors the documented public URL
pattern ``/threads/{slug}.{thread_id}/`` with a visible Sydney-local date).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime
from typing import List, Optional
from zoneinfo import ZoneInfo

SYDNEY = ZoneInfo("Australia/Sydney")

# Example: /threads/ann-hy2026-results-presentation.9022606/
_THREAD_HREF = re.compile(
    r'href="(?P<url>https?://(?:www\.)?hotcopper\.com\.au/threads/'
    r'(?P<slug>[^\"/?#]+)\.(?P<thread_id>\d+)/?)"',
    re.IGNORECASE,
)
_TITLE_IN_ANCHOR = re.compile(
    r'href="https?://(?:www\.)?hotcopper\.com\.au/threads/'
    r'[^\"/?#]+\.\d+/?">\s*(?P<title>[^<]+?)\s*</a>',
    re.IGNORECASE,
)
# data-posted="2026-02-17T08:39:00+11:00" or <time datetime="...">
_DATETIME_ATTR = re.compile(
    r'(?:data-posted|datetime)="(?P<ts>[^"]+)"',
    re.IGNORECASE,
)


@dataclass(frozen=True)
class HotCopperThreadRow:
    """One publicly listed HotCopper thread row."""

    thread_id: str
    title: str
    url: str
    published_at: datetime
    summary: Optional[str] = None


def parse_hotcopper_thread_list(
    html: str,
    *,
    on_date: date,
) -> List[HotCopperThreadRow]:
    """Return thread rows whose Sydney calendar day equals ``on_date``.

    Rows missing a parseable timestamp or title/url are skipped. Body text is
    not required; ``summary`` may be empty.
    """
    rows: List[HotCopperThreadRow] = []
    # Walk each thread link; associate nearest datetime attribute in a window.
    for match in _THREAD_HREF.finditer(html):
        thread_id = match.group("thread_id")
        url = match.group("url")
        if not url.endswith("/"):
            url = url + "/"
        # Prefer timestamp after the href so a previous row's <time> is not
        # wrongly associated with this thread.
        after = html[match.end() : min(len(html), match.end() + 800)]
        before = html[max(0, match.start() - 200) : match.start()]
        window = before + html[match.start() : match.end()] + after
        title_match = _TITLE_IN_ANCHOR.search(window)
        title = (title_match.group("title") if title_match else "").strip()
        if not title:
            # Fall back to slug humanisation
            slug = match.group("slug").replace("-", " ").strip()
            title = slug[:200] if slug else f"HotCopper thread {thread_id}"
        ts_match = _DATETIME_ATTR.search(after) or _DATETIME_ATTR.search(before)
        if not ts_match:
            continue
        published = _parse_timestamp(ts_match.group("ts"))
        if published is None:
            continue
        if published.astimezone(SYDNEY).date() != on_date:
            continue
        rows.append(
            HotCopperThreadRow(
                thread_id=thread_id,
                title=title[:500],
                url=url,
                published_at=published,
                summary=None,
            )
        )
    # Stable unique by thread_id (first wins)
    seen: set[str] = set()
    unique: List[HotCopperThreadRow] = []
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
        parsed = parsed.replace(tzinfo=SYDNEY)
    return parsed
