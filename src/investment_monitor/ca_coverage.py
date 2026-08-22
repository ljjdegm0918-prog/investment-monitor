"""Evidence-based coverage metrics for Canadian disclosure collection."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Iterable, Mapping, Sequence


def calculate_ca_coverage(
    universe: Mapping[str, Any] | None,
    items: Iterable[Mapping[str, Any]],
    *,
    source_statuses: Sequence[Mapping[str, Any]] = (),
    now: datetime | None = None,
) -> Mapping[str, Any]:
    """Calculate transparent Canada coverage and cap the rating at ``high``.

    The function deliberately measures evidence instead of connector
    registration.  A Canadian source cannot be called complete without a
    SEDAR+-equivalent reconciliation contract, which this free-source design
    does not have.
    """
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    cutoff = current - timedelta(days=30)
    universe_items = list((universe or {}).get("items") or ())
    exchanges: Dict[str, set[str]] = {
        "TSX": set(), "TSXV": set(), "CSE": set()
    }
    ir_pages = set()
    feeds = set()
    historical_delisted = 0
    for issuer in universe_items:
        symbol = str(issuer.get("symbol") or issuer.get("ticker") or "").upper()
        listings = issuer.get("listings") or ({"exchange": issuer.get("exchange")},)
        for listing in listings:
            listing_status = str(
                (listing or {}).get("status") or issuer.get("status") or "active"
            ).casefold()
            if listing_status == "delisted":
                historical_delisted += 1
                continue
            exchange = str((listing or {}).get("exchange") or "").upper()
            listing_symbol = str(
                (listing or {}).get("symbol") or symbol
            ).upper()
            if listing_symbol and exchange in exchanges:
                exchanges[exchange].add(listing_symbol)
        if issuer.get("investor_relations_url"):
            ir_pages.add(symbol)
        if issuer.get("announcement_feed_url") or issuer.get("ir_feed_url"):
            feeds.add(symbol)

    source_counts: Dict[str, int] = {}
    recent_issuers = set()
    verified = 0
    single_source = 0
    missing_attachments = 0
    issuers_with_any_source = set()
    total = 0
    for item in items:
        if str(item.get("market") or "").lower() != "ca":
            continue
        total += 1
        source = str(item.get("source") or "unknown")
        source_counts[source] = source_counts.get(source, 0) + 1
        ticker = str(item.get("ticker") or "").upper()
        if ticker:
            issuers_with_any_source.add(ticker)
        metadata = item.get("raw_metadata") or {}
        if not isinstance(metadata, Mapping):
            metadata = {}
        if metadata.get("cross_verified") or int(item.get("dedupe_count") or 1) > 1:
            verified += 1
        else:
            single_source += 1
        attachments = metadata.get("attachment_urls") or metadata.get("attachments")
        if metadata.get("attachments_may_be_missing") or not attachments:
            missing_attachments += 1
        published = _parse_datetime(item.get("published_at"))
        if published and published >= cutoff:
            if ticker:
                recent_issuers.add(ticker)

    incomplete = sum(
        1
        for status in source_statuses
        if str(status.get("status") or "") in {
            "partial", "unavailable", "temporarily_unavailable", "disabled", "stub"
        }
    )
    covered_exchanges = sum(bool(symbols) for symbols in exchanges.values())
    universe_total = len({s for values in exchanges.values() for s in values})
    if not universe_total or not total:
        rating = "unavailable" if not universe_total else "partial"
    elif covered_exchanges == 3 and feeds and len(feeds) / universe_total >= 0.8:
        rating = "high"
    else:
        rating = "partial"
    return {
        "rating": rating,
        "maximum_rating": "high",
        "listed_companies_total": universe_total,
        "historical_delisted_listings": historical_delisted,
        "ir_pages_found": len(ir_pages),
        "usable_announcement_feeds": len(feeds),
        "issuers_with_announcements_30d": len(recent_issuers),
        "issuers_with_any_source": len(issuers_with_any_source),
        "source_item_counts": dict(sorted(source_counts.items())),
        "cross_verified_items": verified,
        "single_source_items": single_source,
        "missing_attachment_items": missing_attachments,
        "incomplete_source_count": incomplete,
        "exchange_coverage": {
            exchange: {
                "listed": len(symbols),
                "with_feed": len(symbols & feeds),
                "with_source": len(symbols & (feeds | issuers_with_any_source)),
                "ratio": (len(symbols & feeds) / len(symbols)) if symbols else 0.0,
                "source_ratio": (
                    len(symbols & (feeds | issuers_with_any_source)) / len(symbols)
                    if symbols else 0.0
                ),
            }
            for exchange, symbols in exchanges.items()
        },
    }


def _parse_datetime(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None else parsed
