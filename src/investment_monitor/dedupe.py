"""Cross-source soft dedupe for the information feed.

Dedupe is display-only and annotate-only: every database row stays in the
database AND in the feed list (1:1, totals untouched). Items that share a
robust identity key each get an "Also seen on …" annotation listing the other
members of their group. Keys prefer the 14-digit Korean disclosure receipt
number (rcept_no / acpt_no) shared by OpenDART and KIND. For UK, filings use
RNS ids (Investegate), Companies House transaction ids, or a same-source
title fallback; Companies House and Investegate are never paired by title
alone. For HK, hkexnews filings use NEWS_ID and hkex_di form serial;
hkexnews and hkex_di are never paired by title. News pairs on ticker + local
day + normalized title. For TW, TWSE and TPEx filings share no cross-source
identity, so their title fallback is source-scoped and the two boards are
never annotated against each other; same-source title fallback pairs on
ticker + Taipei day + normalized title. TW news (yahoo_tw / google_news_tw)
pairs across sources on ticker + Taipei day + normalized title. For CA, no
disclosure connector is wired (SEDAR+ A3 spike), so regulatory filings never
get a key and are never annotated; CA news (yahoo_ca / google_news_ca)
pairs across sources on ticker + Toronto day + normalized title. For AU,
the only wired disclosure source is asx_announcements, which pairs on its
stable ASX document key, or on a source-scoped title fallback (ticker +
Sydney day + normalized title); AU news (yahoo_au / google_news_au) pairs
across sources on ticker + Sydney day + normalized title. For FR,
the only wired disclosure source is amf_oam, which pairs on its stable OAM
document id, or on a source-scoped title fallback (ticker + Paris day +
normalized title); FR news (yahoo_fr / google_news_fr) pairs across sources
on ticker + Paris day + normalized title.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple
from zoneinfo import ZoneInfo

KST = ZoneInfo("Asia/Seoul")
LONDON = ZoneInfo("Europe/London")
HKT = ZoneInfo("Asia/Hong_Kong")
TAIPEI = ZoneInfo("Asia/Taipei")
TORONTO = ZoneInfo("America/Toronto")
SYDNEY = ZoneInfo("Australia/Sydney")
PARIS = ZoneInfo("Europe/Paris")
RECEIPT_LENGTH = 14

FILING_SOURCE_PRIORITY = {
    "dart": 0,
    "investegate": 1,
    "companies_house": 2,
    "kind": 3,
    "sec": 4,
    "hkexnews": 5,
    "hkex_di": 6,
    "twse_material": 7,
    "tpex_material": 8,
    "asx_announcements": 9,
    "amf_oam": 10,
}
NEWS_SOURCE_PRIORITY = {
    "naver_news": 0,
    "yahoo_uk": 1,
    "news": 2,
    "hankyung": 3,
    "thebell": 4,
    "yahoo_hk": 5,
    "yahoo_tw": 6,
    "google_news_tw": 7,
    "yahoo_ca": 8,
    "google_news_ca": 9,
    "yahoo_au": 10,
    "google_news_au": 11,
    "yahoo_fr": 12,
    "google_news_fr": 13,
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
    "yahoo_hk": "Yahoo Finance HK",
    "hkexnews": "HKEXnews (HKEX)",
    "hkex_di": "Disclosure of Interests (HKEX)",
    "twse_material": "TWSE OpenAPI (material)",
    "tpex_material": "TPEx OpenAPI (material)",
    "yahoo_tw": "Yahoo Finance TW",
    "google_news_tw": "Google News (TW)",
    "yahoo_ca": "Yahoo Finance CA",
    "google_news_ca": "Google News (CA)",
    "asx_announcements": "ASX announcements",
    "yahoo_au": "Yahoo Finance AU",
    "google_news_au": "Google News (AU)",
    "amf_oam": "AMF OAM",
    "yahoo_fr": "Yahoo Finance FR",
    "google_news_fr": "Google News (FR)",
}

_FULLWIDTH_SPACE = "\u3000"
_NBSP = "\u00a0"
_TRAILING_ETC = re.compile(r"\s+등\s*$")


def dedupe_key(item: Mapping[str, Any]) -> Optional[str]:
    """Return a stable cross-source key, or None when not deduplicable."""
    market = str(item.get("market") or "")
    if market not in {"kr", "uk", "hk", "tw", "ca", "au", "fr"}:
        return None
    source_type = str(item.get("source_type") or "")
    if source_type == "regulatory_filing":
        return _filing_key(item, market)
    if source_type == "news":
        return _news_key(item, market)
    return None


def annotate_feed_items(
    items: Sequence[Mapping[str, Any]],
    *,
    enabled: bool = True,
) -> List[Mapping[str, Any]]:
    """Keep every row and annotate cross-source duplicates as "also seen on".

    Soft dedupe never drops rows and never changes totals: rows sharing a
    ``dedupe_key`` each get ``also_seen_on`` / ``also_seen_on_labels`` for the
    other members of their group. Annotation is based on the raw rows of the
    current page only; the same key split across pages may not see each other
    (totals and page sizes stay correct either way).
    """
    if not enabled:
        return [dict(item) for item in items]

    groups: Dict[str, List[Mapping[str, Any]]] = {}
    for item in items:
        key = dedupe_key(item)
        if key is None:
            continue
        groups.setdefault(key, []).append(item)

    annotated: List[Mapping[str, Any]] = []
    for item in items:
        entry = dict(item)
        key = dedupe_key(item)
        if key is None:
            annotated.append(entry)
            continue
        group = groups[key]
        others = [other for other in group if other is not item]
        entry["dedupe_count"] = len(group)
        if others:
            entry["also_seen_on"] = [
                str(other["source"]) for other in others
            ]
            entry["also_seen_on_labels"] = [
                SOURCE_DISPLAY_LABELS.get(
                    str(other["source"]),
                    str(other["source"]),
                )
                for other in others
            ]
        annotated.append(entry)
    return annotated


def fold_feed_items(
    items: Sequence[Mapping[str, Any]],
    *,
    enabled: bool = True,
) -> List[Mapping[str, Any]]:
    """Deprecated alias for :func:`annotate_feed_items`.

    The old "fold to one primary" behavior is gone: every row is kept and
    duplicates are annotated instead of collapsed.
    """
    return annotate_feed_items(items, enabled=enabled)


def normalize_title(value: Any) -> str:
    """Normalize a title for fallback identity comparison."""
    text = str(value or "").replace(_FULLWIDTH_SPACE, " ").replace(
        _NBSP, " "
    )
    text = re.sub(r"\s+", " ", text).strip().lower()
    return _TRAILING_ETC.sub("", text)


def _filing_key(item: Mapping[str, Any], market: str) -> Optional[str]:
    if market == "kr":
        return _kr_filing_key(item)
    if market == "hk":
        return _hk_filing_key(item)
    if market == "tw":
        return _tw_filing_key(item)
    if market == "ca":
        # No CA disclosure connector is wired (SEDAR+ A3 spike); a stray
        # regulatory_filing row must never be cross-annotated.
        return None
    if market == "au":
        return _au_filing_key(item)
    if market == "fr":
        return _fr_filing_key(item)
    return _uk_filing_key(item)


def _fr_filing_key(item: Mapping[str, Any]) -> Optional[str]:
    """FR filings pair on the stable AMF OAM document id, or a fallback.

    ``amf_oam`` is the only wired FR disclosure source; its document id
    (``raw_metadata.document_id`` or ``external_id``) is the primary
    identity. Without one, the fallback is source-scoped (source + ticker +
    Paris day + normalized title), so a hypothetical second FR disclosure
    source is never cross-annotated by title.
    """
    source = str(item.get("source") or "")
    metadata = item.get("raw_metadata") or {}
    document_id = str(
        metadata.get("document_id") or item.get("external_id") or ""
    ).strip()
    if document_id:
        return f"fr:filing:oam:{document_id}"
    title = normalize_title(item.get("title"))
    day = _local_day(item, PARIS)
    if title and day:
        return (
            f"fr:filing:title:{source}:"
            f"{item.get('ticker')}:{day}:{title}"
        )
    return None


def _au_filing_key(item: Mapping[str, Any]) -> Optional[str]:
    """AU filings pair on the stable ASX document key, or a title fallback.

    ``asx_announcements`` is the only wired AU disclosure source; its
    document key (``raw_metadata.document_key`` or ``external_id``) is the
    primary identity. Without one, the fallback is source-scoped (source +
    ticker + Sydney day + normalized title), so a hypothetical second AU
    disclosure source is never cross-annotated by title.
    """
    source = str(item.get("source") or "")
    metadata = item.get("raw_metadata") or {}
    document_key = str(
        metadata.get("document_key") or item.get("external_id") or ""
    ).strip()
    if document_key:
        return f"au:filing:asx:{document_key}"
    title = normalize_title(item.get("title"))
    day = _local_day(item, SYDNEY)
    if title and day:
        return (
            f"au:filing:title:{source}:"
            f"{item.get('ticker')}:{day}:{title}"
        )
    return None


def _kr_filing_key(item: Mapping[str, Any]) -> Optional[str]:
    receipt = _receipt_number(item)
    if receipt is not None:
        return f"kr-filing:{receipt}"
    title = normalize_title(item.get("title"))
    day = _local_day(item, KST)
    if title and day:
        return f"kr-filing:{item.get('ticker')}|{day}|{title}"
    return None


def _uk_filing_key(item: Mapping[str, Any]) -> Optional[str]:
    metadata = item.get("raw_metadata") or {}
    rns_raw = metadata.get("rns_id") or (
        item.get("external_id")
        if str(item.get("source") or "") == "investegate"
        else None
    )
    rns_digits = re.sub(r"\D", "", str(rns_raw or ""))
    if rns_digits and len(rns_digits) >= 6:
        return f"uk:filing:rns:{rns_digits}"
    if str(item.get("source") or "") == "companies_house":
        transaction_id = str(item.get("external_id") or "").strip()
        if transaction_id:
            return f"uk:filing:ch:{transaction_id}"
    title = normalize_title(item.get("title"))
    day = _local_day(item, LONDON)
    if title and day:
        return (
            f"uk:filing:title:{item.get('source')}:"
            f"{item.get('ticker')}:{day}:{title}"
        )
    return None


def _hk_filing_key(item: Mapping[str, Any]) -> Optional[str]:
    source = str(item.get("source") or "")
    metadata = item.get("raw_metadata") or {}
    if source == "hkexnews":
        news_id = str(
            metadata.get("news_id") or item.get("external_id") or ""
        ).strip()
        if news_id:
            return f"hk:filing:news_id:{news_id}"
    if source == "hkex_di":
        serial = str(item.get("external_id") or "").strip()
        if serial:
            return f"hk:filing:di:{serial}"
    title = normalize_title(item.get("title"))
    day = _local_day(item, HKT)
    if title and day:
        return (
            f"hk:filing:title:{source}:"
            f"{item.get('ticker')}:{day}:{title}"
        )
    return None


def _tw_filing_key(item: Mapping[str, Any]) -> Optional[str]:
    """TW filings pair on a source-scoped title fallback only.

    ``twse_material`` and ``tpex_material`` share no cross-source receipt or
    NEWS_ID, and listing vs OTC boards should never be annotated against each
    other by title, so the source is part of the key. Same source, same
    ticker, same Taipei day and same normalized title share a key.
    """
    source = str(item.get("source") or "")
    title = normalize_title(item.get("title"))
    day = _local_day(item, TAIPEI)
    if title and day:
        return (
            f"tw:filing:title:{source}:"
            f"{item.get('ticker')}:{day}:{title}"
        )
    return None


def _news_key(item: Mapping[str, Any], market: str) -> Optional[str]:
    zone = (
        KST
        if market == "kr"
        else HKT
        if market == "hk"
        else TAIPEI
        if market == "tw"
        else TORONTO
        if market == "ca"
        else SYDNEY
        if market == "au"
        else PARIS
        if market == "fr"
        else LONDON
    )
    title = normalize_title(item.get("title"))
    day = _local_day(item, zone)
    if title and day:
        return f"{market}-news:{item.get('ticker')}|{day}|{title}"
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


def _local_day(
    item: Mapping[str, Any],
    zone: ZoneInfo,
) -> Optional[str]:
    raw = item.get("effective_at") or item.get("published_at")
    if not raw:
        return None
    try:
        parsed = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(zone).date().isoformat()


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
