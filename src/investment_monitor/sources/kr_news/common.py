"""Shared helpers for KR news connectors."""

from __future__ import annotations

import html
import re
from datetime import datetime
from typing import Optional

DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/126.0 Safari/537.36"
)


def normalize_kr_ticker(ticker: str) -> str:
    """Normalize a KR stock code to six digits (5930 -> 005930)."""
    raw = ticker.strip()
    return raw.zfill(6) if raw.isdigit() else raw


def strip_tags(value: str) -> str:
    """Strip HTML tags and unescape entities from a cell fragment."""
    return html.unescape(re.sub(r"<[^>]+>", " ", value)).strip()


def parse_kst_datetime(value: str) -> Optional[datetime]:
    """Parse a KST date string ('YYYY.MM.DD HH:MM' or 'YYYY-MM-DD HH:MM')."""
    normalized = value.strip().replace("-", ".").replace("/", ".")
    for pattern in (
        "%Y.%m.%d %H:%M",
        "%Y.%m.%d",
    ):
        try:
            parsed = datetime.strptime(normalized, pattern)
        except ValueError:
            continue
        from zoneinfo import ZoneInfo

        return parsed.replace(tzinfo=ZoneInfo("Asia/Seoul"))
    return None
