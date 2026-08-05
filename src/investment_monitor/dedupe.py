"""Cross-source soft dedupe for the information feed.

Dedupe is display-only: every source row stays in the database, and only the
feed assembly folds items that share a robust identity key. Keys prefer the
14-digit Korean disclosure receipt number (rcept_no / acpt_no) shared by
OpenDART and KIND; the title fallback is only used when neither item has a
receipt number, so unrelated same-title disclosures are never mis-folded.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple
from zoneinfo import ZoneInfo

KST = ZoneInfo("Asia/Seoul")
RECEIPT_LENGTH = 14

FILING_SOURCE_PRIORITY = {
    "dart": 0,
    "investegate": 1,
    "companies_house": 2,
    "kind": 3,
    "sec": 4,
}
NEWS_SOURCE_PRIORITY = {
    "naver_news": 0,
    "yahoo_uk": 1,
    "news": 2,
    "hankyung": 3,
    "thebell": 4,
}
SOURCE_DISPLAY_LABELS = {
    "dart": "OpenDART",
    "investegate": "Investegate",
    "companies_house": "Companies House",
    "kind": "KIND (KRX)",
    "sec": "SEC EDGAR",
    "naver_news": "Naver Finance",
    "news": "Finnhub News",
    "hankyung": "Hankyung",
    "thebell": "TheBell",
    "yahoo_uk": "Yahoo Finance UK",
}

_FULLWIDTH_SPACE = "\u3000"
_NBSP = "\u00a0"
_TRAILING_ETC = re.compile(r"\s+등\s*$")


def dedupe_key(item: Mapping[str, Any]) -> Optional[str]:
    """Return a stable cross-source key, or None when not deduplicable."""
    if str(item.get("market") or "") != "kr":
        return None
    source_type = str(item.get("source_type") or "")
    if source_type == "regulatory_filing":
        return _filing_key(item)
    if source_type == "news":
        return _news_key(item)
    return None


def fold_feed_items(
    items: Sequence[Mapping[str, Any]],
    *,
    enabled: bool = True,
) -> List[Mapping[str, Any]]:
    """Fold deduplicated groups into a primary item with also_from fields."""
    if not enabled:
        return [dict(item) for item in items]

    groups: Dict[str, List[Mapping[str, Any]]] = {}
    order: List[Tuple[str, Optional[str], Optional[Mapping[str, Any]]]] = []
    for item in items:
        key = dedupe_key(item)
        if key is None:
            order.append(("single", None, item))
            continue
        if key not in groups:
            groups[key] = []
            order.append(("group", key, None))
        groups[key].append(item)

    folded: List[Mapping[str, Any]] = []
    for kind, key, single in order:
        if kind == "single":
            folded.append(dict(single or {}))
            continue
        if key is None:
            continue
        group = groups[key]
        primary = _pick_primary(group)
        if len(group) > 1:
            others = [other for other in group if other is not primary]
            primary = dict(primary)
            primary["also_from"] = [
                str(other["source"]) for other in others
            ]
            primary["also_from_labels"] = [
                SOURCE_DISPLAY_LABELS.get(
                    str(other["source"]),
                    str(other["source"]),
                )
                for other in others
            ]
            primary["dedupe_count"] = len(group)
        else:
            primary = dict(primary)
        folded.append(primary)
    return folded


def normalize_title(value: Any) -> str:
    """Normalize a title for fallback identity comparison."""
    text = str(value or "").replace(_FULLWIDTH_SPACE, " ").replace(
        _NBSP, " "
    )
    text = re.sub(r"\s+", " ", text).strip()
    return _TRAILING_ETC.sub("", text)


def _filing_key(item: Mapping[str, Any]) -> Optional[str]:
    receipt = _receipt_number(item)
    if receipt is not None:
        return f"kr-filing:{receipt}"
    title = normalize_title(item.get("title"))
    day = _kst_day(item)
    if title and day:
        return f"kr-filing:{item.get('ticker')}|{day}|{title}"
    return None


def _news_key(item: Mapping[str, Any]) -> Optional[str]:
    title = normalize_title(item.get("title"))
    day = _kst_day(item)
    if title and day:
        return f"kr-news:{item.get('ticker')}|{day}|{title}"
    return None


def _receipt_number(item: Mapping[str, Any]) -> Optional[str]:
    metadata = item.get("raw_metadata") or {}
    raw = (
        metadata.get("rcept_no")
        or metadata.get("acpt_no")
        or item.get("external_id")
    )
    digits = re.sub(r"\D", "", str(raw or ""))
    return digits if len(digits) == RECEIPT_LENGTH else None


def _kst_day(item: Mapping[str, Any]) -> Optional[str]:
    raw = item.get("effective_at") or item.get("published_at")
    if not raw:
        return None
    try:
        parsed = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(KST).date().isoformat()


def _pick_primary(group: Sequence[Mapping[str, Any]]) -> Mapping[str, Any]:
    source_type = str(group[0].get("source_type") or "")
    priority = (
        FILING_SOURCE_PRIORITY
        if source_type == "regulatory_filing"
        else NEWS_SOURCE_PRIORITY
    )

    def rank(item: Mapping[str, Any]) -> Tuple[int, int]:
        return (
            priority.get(str(item.get("source")), 99),
            group.index(item),
        )

    return min(group, key=rank)
