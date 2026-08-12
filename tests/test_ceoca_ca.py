"""Unit tests for CEO.ca (CA) live connector + Toronto day parser."""

from __future__ import annotations

import json
import unittest
from datetime import date, datetime
from pathlib import Path
from typing import Any, Mapping, Optional
from zoneinfo import ZoneInfo

from investment_monitor.dedupe import annotate_feed_items, dedupe_key
from investment_monitor.models import MARKET_CA, CollectionRequest
from investment_monitor.registry import create_default_registry
from investment_monitor.sources.ceoca_ca import (
    CeocaCaConnector,
    parse_ceoca_spiel_payload,
)
from investment_monitor.web_repository import normalize_ca_ticker

FIXTURE = (
    Path(__file__).resolve().parent
    / "fixtures"
    / "ceoca"
    / "shop_spiels_sample.json"
)
TORONTO = ZoneInfo("America/Toronto")


class CeocaCaTests(unittest.TestCase):
    def test_normalize_root_ticker(self) -> None:
        self.assertEqual(normalize_ca_ticker("SHOP.TO"), "SHOP")
        self.assertEqual(normalize_ca_ticker("shop"), "SHOP")

    def test_parser_filters_toronto_day(self) -> None:
        payload = json.loads(FIXTURE.read_text(encoding="utf-8"))
        rows = parse_ceoca_spiel_payload(payload, on_date=date(2026, 8, 5))
        self.assertEqual(len(rows), 2)
        ids = {row.spiel_id for row in rows}
        self.assertEqual(
            ids,
            {"spiel-aug5-morning", "spiel-aug5-evening"},
        )
        for row in rows:
            self.assertTrue(row.body)
            self.assertEqual(row.channel, "shop")
            self.assertEqual(
                row.published_at.astimezone(TORONTO).date(),
                date(2026, 8, 5),
            )

    def test_parser_empty_for_other_day(self) -> None:
        payload = json.loads(FIXTURE.read_text(encoding="utf-8"))
        rows = parse_ceoca_spiel_payload(payload, on_date=date(2026, 8, 6))
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].spiel_id, "spiel-aug6-early")

    def test_map_rows_builds_community_items(self) -> None:
        payload = json.loads(FIXTURE.read_text(encoding="utf-8"))
        rows = parse_ceoca_spiel_payload(payload, on_date=date(2026, 8, 5))
        connector = CeocaCaConnector(fetch_json=_fixture_fetch)
        items = connector.map_rows(
            rows,
            ticker="SHOP.TO",
            collected_at=datetime(2026, 8, 5, 12, 0, tzinfo=TORONTO),
        )
        self.assertEqual(len(items), 2)
        first = items[0]
        self.assertEqual(first.source, "ceoca_ca")
        self.assertEqual(first.source_type, "community")
        self.assertEqual(first.document_type, "community_post")
        self.assertEqual(first.market, MARKET_CA)
        self.assertEqual(first.tickers, ("SHOP",))
        self.assertTrue(first.title)
        self.assertEqual(first.url, "https://ceo.ca/SHOP")
        self.assertTrue(first.external_id.startswith("ceoca-"))
        self.assertEqual(first.raw_metadata["spiel_id"], rows[0].spiel_id)
        self.assertEqual(
            first.raw_metadata["url_pattern"],
            "https://ceo.ca/{CHANNEL}",
        )

    def test_collect_with_mocked_http(self) -> None:
        connector = CeocaCaConnector(fetch_json=_fixture_fetch)
        request = CollectionRequest(
            tickers=("SHOP.TO",),
            start_date=date(2026, 8, 5),
            end_date=date(2026, 8, 5),
            markets={"SHOP": "ca"},
        )
        items = connector.collect(request)
        self.assertEqual(len(items), 2)
        self.assertEqual(connector.status, "live")
        self.assertEqual(connector.last_errors, ())

    def test_collect_skips_non_ca_market(self) -> None:
        connector = CeocaCaConnector(fetch_json=_fixture_fetch)
        request = CollectionRequest(
            tickers=("SHOP",),
            start_date=date(2026, 8, 5),
            end_date=date(2026, 8, 5),
            markets={"SHOP": "us"},
        )
        items = connector.collect(request)
        self.assertEqual(items, [])

    def test_registry_registers_ceoca_ca(self) -> None:
        registry = create_default_registry()
        self.assertIsNotNone(registry.factory_for("ceoca_ca"))
        connector = registry.factory_for("ceoca_ca")()
        self.assertEqual(connector.name, "ceoca_ca")

    def test_pagination_collects_beyond_first_50_page(self) -> None:
        """API fixes 50 spiels/page; collect must paginate past page 1.

        Page 1 holds exactly 50 spiels with two on the target Toronto day;
        page 2 (requested via ``until``) holds two more spiels on the same
        target day. Before the fix the short-page check ``len < page_limit(100)``
        always broke after page 1, so page 2 items were missed. After the fix
        the merged, deduped set must include both pages (4 distinct items).
        """
        connector = CeocaCaConnector(fetch_json=_paginated_fetch)
        request = CollectionRequest(
            tickers=("SHOP.TO",),
            start_date=date(2026, 8, 5),
            end_date=date(2026, 8, 5),
            markets={"SHOP": "ca"},
        )
        items = connector.collect(request)
        self.assertEqual(len(items), 4)
        ids = {item.raw_metadata["spiel_id"] for item in items}
        self.assertEqual(
            ids,
            {
                "p1-target-0",
                "p1-target-1",
                "p2-target-0",
                "p2-target-1",
            },
        )
        # Page 2 was actually fetched (pagination moved past page 1).
        self.assertGreaterEqual(_paginated_fetch.calls, 2)

    def test_pagination_short_last_page_stops(self) -> None:
        """A short (< 50) trailing page terminates pagination without error."""
        calls = {"n": 0}

        def fetch(channel, user_agent, until):
            calls["n"] += 1
            # Full 50-item page 1 (two target-day items) plus one short
            # trailing page that is empty of target-day items.
            if until is None:
                return _paginated_payload(
                    n_spiels=50,
                    target_ids=("p1-target-0", "p1-target-1"),
                    target_ms=(_AUG5_EVENING_MS, _AUG5_EVENING_MS + 1),
                )
            return _paginated_payload(
                n_spiels=10,
                target_ids=(),
                target_ms=(),
            )

        connector = CeocaCaConnector(fetch_json=fetch)
        request = CollectionRequest(
            tickers=("SHOP.TO",),
            start_date=date(2026, 8, 5),
            end_date=date(2026, 8, 5),
            markets={"SHOP": "ca"},
        )
        items = connector.collect(request)
        self.assertEqual(len(items), 2)
        ids = {item.raw_metadata["spiel_id"] for item in items}
        self.assertEqual(ids, {"p1-target-0", "p1-target-1"})

    def test_community_soft_dedupe_uses_spiel_id(self) -> None:
        published = "2026-08-05T14:00:00+00:00"
        first = {
            "source": "ceoca_ca",
            "source_type": "community",
            "external_id": "ceoca-spiel-aug5-morning",
            "ticker": "SHOP",
            "market": "ca",
            "title": "@bullish_ca: Shopify looks strong",
            "published_at": published,
            "effective_at": published,
            "raw_metadata": {"spiel_id": "spiel-aug5-morning"},
        }
        second = {
            **first,
            "external_id": "ceoca-spiel-aug5-morning-dup",
        }
        self.assertEqual(dedupe_key(first), dedupe_key(second))
        self.assertEqual(
            dedupe_key(first),
            "ca:community:ceoca:spiel-aug5-morning",
        )
        annotated = annotate_feed_items([first, second])
        self.assertEqual(len(annotated), 2)
        self.assertEqual(annotated[0]["also_seen_on"], ["ceoca_ca"])
        self.assertEqual(
            annotated[0]["also_seen_on_labels"],
            ["CEO.ca (CA)"],
        )


def _fixture_fetch(
    channel: str,
    user_agent: str,
    until: Optional[int],
) -> Mapping[str, Any]:
    payload = json.loads(FIXTURE.read_text(encoding="utf-8"))
    if until is not None:
        spiels = [
            entry
            for entry in payload["spiels"]
            if int(entry["timestamp"]) <= until
        ]
        return {**payload, "spiels": spiels}
    return payload


# AUG5 timestamps on the Toronto day 2026-08-05 (UTC epoch ms). Evening value
# mirrors the sample fixture; mid/morning values fall earlier on the same day.
_AUG5_EVENING_MS = 1785981600000
_AUG5_MID_MS = 1785950000000
_AUG5_MORNING_MS = 1785938400000


def _spiel(spiel_id: str, timestamp_ms: int) -> Mapping[str, Any]:
    return {
        "channel": "shop",
        "spiel_id": spiel_id,
        "spiel": f"Spiel {spiel_id} body text.",
        "name": "@test_user",
        "timestamp": timestamp_ms,
    }


def _paginated_payload(
    *,
    n_spiels: int,
    target_ids: Sequence[str],
    target_ms: Sequence[int],
) -> Mapping[str, Any]:
    """Build a page of ``n_spiels`` entries.

    ``target_ids``/``target_ms`` place a few entries on the target Toronto
    day (2026-08-05); the rest are filler on a LATER day (2026-08-06) so they
    are not collected and do not trip the ``oldest_day < start_date`` break.
    """
    spiels: list[Mapping[str, Any]] = [
        _spiel(target_ids[i], int(target_ms[i]))
        for i in range(len(target_ids))
    ]
    # Filler on a later day (after the target day) so it never matches.
    filler_ms = _AUG5_EVENING_MS + 86400_000 + len(spiels)
    while len(spiels) < n_spiels:
        filler_ms += 1
        spiels.append(_spiel(f"filler-{len(spiels)}", filler_ms))
    return {"channel": "shop", "total_spiels": n_spiels, "spiels": spiels}


class _PaginatedFetch:
    """Stateful fetch mocking page 1 (50 spiels) + short page 2 (40 spiels).

    Page 1: two target-day items at the evening timestamp. Page 2 (``until``
    before the evening timestamp): two more target-day items at mid/morning.
    Page 2 is short (< 50) so pagination stops there, proving both pages were
    fetched and merged.
    """

    calls = 0

    def __call__(
        self,
        channel: str,
        user_agent: str,
        until: Optional[int],
    ) -> Mapping[str, Any]:
        type(self).calls += 1
        if until is None:
            return _paginated_payload(
                n_spiels=50,
                target_ids=("p1-target-0", "p1-target-1"),
                target_ms=(_AUG5_EVENING_MS, _AUG5_EVENING_MS + 1),
            )
        return _paginated_payload(
            n_spiels=40,
            target_ids=("p2-target-0", "p2-target-1"),
            target_ms=(_AUG5_MID_MS, _AUG5_MORNING_MS),
        )


_paginated_fetch = _PaginatedFetch()


if __name__ == "__main__":
    unittest.main()
