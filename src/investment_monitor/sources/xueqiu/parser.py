"""Parse public Xueqiu status-list HTML (fixture / future live page).

Synthetic fixture mirrors the documented public symbol page pattern
``https://xueqiu.com/S/{SYMBOL}`` with status links
``https://xueqiu.com/{user_id}/{status_id}`` and local-date timestamps.
CN pages use the Asia/Shanghai calendar day; HK pages use
Asia/Hong_Kong (mirrors the day-filter requirement from the spike).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime
from typing import List, Optional
from zoneinfo import ZoneInfo

SHANGHAI = ZoneInfo("Asia/Shanghai")
HONG_KONG = ZoneInfo("Asia/Hong_Kong")

# Example: https://xueqiu.com/1012345678/2345678901 (user_id/status_id)
_STATUS_HREF = re.compile(
    r'href="(?P<url>https?://(?:www\.)?xueqiu\.com/'
    r'(?P<user_id>\d+)/(?P<status_id>\d+)/?)"',
    re.IGNORECASE,
)
_TITLE_IN_ANCHOR = re.compile(
    r'href="https?://(?:www\.)?xueqiu\.com/\d+/\d+/?">'
    r'\s*(?P<title>[^<]+?)\s*</a>',
    re.IGNORECASE,
)
# data-posted="2026-02-17T10:39:00+08:00" or <time datetime="...">
_DATETIME_ATTR = re.compile(
    r'(?:data-posted|datetime)="(?P<ts>[^"]+)"',
    re.IGNORECASE,
)

_SUPPORTED_MARKETS = {"cn", "hk"}


@dataclass(frozen=True)
class XueqiuPostRow:
    """One publicly listed Xueqiu status row."""

    status_id: str
    title: str
    url: str
    published_at: datetime
    summary: Optional[str] = None


def parse_xueqiu_status_list(
    html: str,
    *,
    on_date: date,
    market: str,
) -> List[XueqiuPostRow]:
    """Return status rows whose local calendar day equals ``on_date``.

    ``market`` selects the day-filter zone: ``"cn"`` → Asia/Shanghai,
    ``"hk"`` → Asia/Hong_Kong. Rows missing a parseable timestamp or
    title/url are skipped. Body text is not required; ``summary`` may be
    empty.
    """
    zone = _market_zone(market)
    rows: List[XueqiuPostRow] = []
    # Walk each status link; associate nearest datetime attribute in a window.
    for match in _STATUS_HREF.finditer(html):
        status_id = match.group("status_id")
        url = match.group("url")
        if not url.endswith("/"):
            url = url + "/"
        after = html[match.end() : min(len(html), match.end() + 800)]
        before = html[max(0, match.start() - 200) : match.start()]
        window = before + html[match.start() : match.end()] + after
        title_match = _TITLE_IN_ANCHOR.search(window)
        title = (title_match.group("title") if title_match else "").strip()
        if not title:
            title = f"Xueqiu status {status_id}"[:500]
        ts_match = _DATETIME_ATTR.search(after) or _DATETIME_ATTR.search(before)
        if not ts_match:
            continue
        published = _parse_timestamp(ts_match.group("ts"), zone)
        if published is None:
            continue
        if published.astimezone(zone).date() != on_date:
            continue
        rows.append(
            XueqiuPostRow(
                status_id=status_id,
                title=title[:500],
                url=url,
                published_at=published,
                summary=None,
            )
        )
    seen: set[str] = set()
    unique: List[XueqiuPostRow] = []
    for row in rows:
        if row.status_id in seen:
            continue
        seen.add(row.status_id)
        unique.append(row)
    return unique


def _market_zone(market: str) -> ZoneInfo:
    if market not in _SUPPORTED_MARKETS:
        raise ValueError(
            f"unsupported xueqiu market {market!r}; expected cn or hk"
        )
    return SHANGHAI if market == "cn" else HONG_KONG


def _parse_timestamp(raw: str, zone: ZoneInfo) -> Optional[datetime]:
    text = str(raw or "").strip().replace("Z", "+00:00")
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=zone)
    return parsed
