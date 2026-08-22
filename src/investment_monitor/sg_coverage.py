"""Evidence-based coverage metrics for Singapore disclosure collection."""

from __future__ import annotations

from collections import Counter
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Iterable, Mapping, Sequence


def calculate_sg_coverage(
    universe: Mapping[str, Any] | None,
    items: Iterable[Mapping[str, Any]],
    *,
    source_statuses: Sequence[Mapping[str, Any]] = (),
    now: datetime | None = None,
) -> Mapping[str, Any]:
    """Measure SG evidence without equating a few issuers with SGXNET."""
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    cutoff = current - timedelta(days=30)
    universe_items = list((universe or {}).get("items") or ())
    boards: Dict[str, set[str]] = {"Mainboard": set(), "Catalist": set()}
    ir_sites: set[str] = set()
    feeds: set[str] = set()
    for issuer in universe_items:
        ticker = str(issuer.get("ticker") or issuer.get("symbol") or "").upper()
        board = _board_name(issuer.get("board") or issuer.get("exchange"))
        if ticker and board in boards:
            boards[board].add(ticker)
        if ticker and issuer.get("investor_relations_url"):
            ir_sites.add(ticker)
        if ticker and (
            issuer.get("announcement_feed_url") or issuer.get("ir_feed_url")
        ):
            feeds.add(ticker)

    source_counts: Counter[str] = Counter()
    recent_count = official_count = third_party_only = 0
    missing_attachments = cross_verified = 0
    issuer_sources: Dict[str, set[str]] = {}
    daily_counts: Counter[str] = Counter()
    oldest: datetime | None = None
    total = 0
    for item in items:
        if str(item.get("market") or "").lower() != "sg":
            continue
        total += 1
        source = str(item.get("source") or "unknown")
        ticker = str(item.get("ticker") or "").upper()
        source_counts[source] += 1
        if ticker:
            issuer_sources.setdefault(ticker, set()).add(source)
            if source == "sg_ir":
                ir_sites.add(ticker)
                feeds.add(ticker)
        metadata = item.get("raw_metadata") or {}
        if not isinstance(metadata, Mapping):
            metadata = {}
        tier = metadata.get("source_tier")
        official = bool(
            metadata.get("official_document")
            or metadata.get("is_official")
            or source in {"sgx_announcements", "mas_opera", "sg_edgar"}
        )
        if official:
            official_count += 1
        if tier in {3, 4, "third_party"} and not official:
            third_party_only += 1
        attachments = metadata.get("attachment_urls") or metadata.get("attachments")
        if metadata.get("attachments_may_be_missing") or not attachments:
            missing_attachments += 1
        if metadata.get("cross_verified") or int(item.get("dedupe_count") or 1) > 1:
            cross_verified += 1
        published = _parse_datetime(item.get("published_at"))
        if published:
            oldest = published if oldest is None or published < oldest else oldest
            daily_counts[published.date().isoformat()] += 1
            if published >= cutoff:
                recent_count += 1

    known = {ticker for values in boards.values() for ticker in values}
    without_source = len(known - set(issuer_sources))
    daily_values = list(daily_counts.values())
    variance = 0.0
    if daily_values:
        mean = sum(daily_values) / len(daily_values)
        variance = sum((value - mean) ** 2 for value in daily_values) / len(daily_values)
    incomplete = sum(
        1 for status in source_statuses
        if str(status.get("status") or "") in {
            "partial", "unavailable", "temporarily_unavailable", "disabled", "stub"
        }
    )
    # Without a stable SGXNET enumerator, high requires an explicit external
    # 30-day reconciliation flag; complete is intentionally impossible here.
    reconciled = bool((universe or {}).get("sgx_reconciled_30d"))
    rating = (
        "unavailable" if total == 0
        else "high" if reconciled and official_count and recent_count
        else "partial"
    )
    return {
        "rating": rating,
        "maximum_rating": "high",
        "known_issuers": len(known),
        "mainboard_issuers": len(boards["Mainboard"]),
        "catalist_issuers": len(boards["Catalist"]),
        "ir_sites_found": len(ir_sites),
        "usable_ir_feeds": len(feeds),
        "announcements_30d": recent_count,
        "official_sgx_link_announcements": source_counts["sgx_announcements"],
        "third_party_only_announcements": third_party_only,
        "missing_attachment_announcements": missing_attachments,
        "issuers_without_announcement_source": without_source,
        "cross_verified_ratio": (cross_verified / total) if total else 0.0,
        "source_item_counts": dict(sorted(source_counts.items())),
        "board_coverage": {
            board: {
                "known": len(tickers),
                "with_source": len(tickers & set(issuer_sources)),
                "ratio": (
                    len(tickers & set(issuer_sources)) / len(tickers)
                    if tickers else 0.0
                ),
            }
            for board, tickers in boards.items()
        },
        "daily_announcement_count_variance": variance,
        "oldest_retrievable_at": oldest.isoformat() if oldest else None,
        "incomplete_source_count": incomplete,
    }


def _board_name(value: Any) -> str:
    text = str(value or "").casefold()
    if "catalist" in text:
        return "Catalist"
    if "main" in text:
        return "Mainboard"
    return ""


def _parse_datetime(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None else parsed
