"""Unit tests for Seeking Alpha LIVE combined RSS (no live network)."""

from __future__ import annotations

import unittest
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from investment_monitor.dedupe import annotate_feed_items, dedupe_key
from investment_monitor.models import MARKET_US, CollectionRequest
from investment_monitor.registry import create_default_registry
from investment_monitor.sources.seeking_alpha import (
    SeekingAlphaConnector,
    normalize_us_ticker,
    parse_seeking_alpha_combined_rss,
)

FIXTURE = (
    Path(__file__).resolve().parent
    / "fixtures"
    / "seeking_alpha"
    / "aapl_combined_2026-08-11.xml"
)
NEW_YORK = ZoneInfo("America/New_York")


class SeekingAlphaTests(unittest.TestCase):
    def test_normalize_us_ticker(self) -> None:
        self.assertEqual(normalize_us_ticker("aapl"), "AAPL")
        self.assertEqual(normalize_us_ticker(" AAPL "), "AAPL")

    def test_parser_filters_new_york_day(self) -> None:
        xml_text = FIXTURE.read_text(encoding="utf-8")
        rows = parse_seeking_alpha_combined_rss(
            xml_text, on_date=date(2026, 8, 11)
        )
        self.assertEqual(len(rows), 2)
        ids = {row.content_id for row in rows}
        self.assertEqual(ids, {"4630410", "4932193"})
        for row in rows:
            self.assertTrue(row.title)
            self.assertTrue(row.url)
            self.assertEqual(
                row.published_at.astimezone(NEW_YORK).date(),
                date(2026, 8, 11),
            )

    def test_parser_empty_for_other_day(self) -> None:
        xml_text = FIXTURE.read_text(encoding="utf-8")
        rows = parse_seeking_alpha_combined_rss(
            xml_text, on_date=date(2026, 8, 12)
        )
        self.assertEqual(rows, [])

    def test_collect_uses_injected_fetch(self) -> None:
        xml_text = FIXTURE.read_text(encoding="utf-8")
        connector = SeekingAlphaConnector(fetch_xml=lambda _symbol: xml_text)
        request = CollectionRequest(
            tickers=("AAPL",),
            start_date=date(2026, 8, 11),
            end_date=date(2026, 8, 11),
            markets={"AAPL": "us"},
        )
        items = connector.collect(request)
        self.assertEqual(len(items), 2)
        self.assertEqual(connector.status, "live")
        first = items[0]
        self.assertEqual(first.source, "seeking_alpha")
        self.assertEqual(first.source_type, "community")
        self.assertEqual(first.document_type, "community_post")
        self.assertEqual(first.market, MARKET_US)
        self.assertEqual(first.tickers, ("AAPL",))
        self.assertEqual(
            first.raw_metadata.get("category"), "article_news_rss"
        )

    def test_collect_skips_non_us(self) -> None:
        connector = SeekingAlphaConnector(
            fetch_xml=lambda _symbol: (_ for _ in ()).throw(
                AssertionError("should not fetch")
            )
        )
        request = CollectionRequest(
            tickers=("0700",),
            start_date=date(2026, 8, 11),
            end_date=date(2026, 8, 11),
            markets={"0700": "hk"},
        )
        items = connector.collect(request)
        self.assertEqual(items, [])

    def test_registry_registers_seeking_alpha(self) -> None:
        registry = create_default_registry()
        self.assertIsNotNone(registry.factory_for("seeking_alpha"))
        connector = registry.factory_for("seeking_alpha")()
        self.assertEqual(connector.name, "seeking_alpha")
        self.assertEqual(connector.status, "live")

    def test_community_soft_dedupe_uses_content_id(self) -> None:
        published = "2026-08-11T04:48:04+00:00"
        first = {
            "source": "seeking_alpha",
            "source_type": "community",
            "external_id": "seeking-alpha-market_current-4630410",
            "ticker": "AAPL",
            "market": "us",
            "title": "Apple glass iPhone stays on track",
            "published_at": published,
            "effective_at": published,
            "raw_metadata": {
                "content_id": "4630410",
                "content_kind": "market_current",
            },
        }
        second = {
            **first,
            "external_id": "seeking-alpha-market_current-4630410-dup",
        }
        self.assertEqual(dedupe_key(first), dedupe_key(second))
        self.assertEqual(
            dedupe_key(first),
            "us:community:seeking_alpha:market_current:4630410",
        )
        annotated = annotate_feed_items([first, second])
        self.assertEqual(len(annotated), 2)
        self.assertEqual(annotated[0]["also_seen_on"], ["seeking_alpha"])
        self.assertEqual(
            annotated[0]["also_seen_on_labels"],
            ["Seeking Alpha (US)"],
        )


if __name__ == "__main__":
    unittest.main()
