"""Unit tests for LSE Share Chat UK stub + fixture parser (no live network)."""

from __future__ import annotations

import unittest
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from investment_monitor.dedupe import annotate_feed_items, dedupe_key
from investment_monitor.models import MARKET_UK, CollectionRequest
from investment_monitor.registry import create_default_registry
from investment_monitor.sources.lse_share_chat import (
    LseShareChatConnector,
    parse_lse_share_chat_thread_list,
)
from investment_monitor.web_repository import normalize_uk_ticker

FIXTURE = (
    Path(__file__).resolve().parent
    / "fixtures"
    / "lse_share_chat"
    / "bp_board_2026-02-17.html"
)
LONDON = ZoneInfo("Europe/London")


class LseShareChatTests(unittest.TestCase):
    def test_normalize_root_ticker(self) -> None:
        self.assertEqual(normalize_uk_ticker("BP.L"), "BP")
        self.assertEqual(normalize_uk_ticker("BP."), "BP")
        self.assertEqual(normalize_uk_ticker("VOD.L"), "VOD")
        self.assertEqual(normalize_uk_ticker("vod"), "VOD")

    def test_parser_filters_london_day(self) -> None:
        html = FIXTURE.read_text(encoding="utf-8")
        rows = parse_lse_share_chat_thread_list(
            html, on_date=date(2026, 2, 17)
        )
        self.assertEqual(len(rows), 2)
        ids = {row.thread_id for row in rows}
        self.assertEqual(ids, {"9022606", "9111111"})
        for row in rows:
            self.assertTrue(row.title)
            self.assertTrue(
                row.url.startswith("https://www.lse.co.uk/ShareChat/thread/")
            )
            self.assertEqual(
                row.published_at.astimezone(LONDON).date(),
                date(2026, 2, 17),
            )

    def test_parser_empty_for_other_day(self) -> None:
        html = FIXTURE.read_text(encoding="utf-8")
        rows = parse_lse_share_chat_thread_list(
            html, on_date=date(2026, 2, 18)
        )
        self.assertEqual(rows, [])

    def test_map_rows_builds_community_items(self) -> None:
        html = FIXTURE.read_text(encoding="utf-8")
        rows = parse_lse_share_chat_thread_list(
            html, on_date=date(2026, 2, 17)
        )
        connector = LseShareChatConnector()
        items = connector.map_rows_for_tests(
            rows,
            ticker="BP.L",
            collected_at=datetime(2026, 2, 17, 12, 0, tzinfo=LONDON),
        )
        self.assertEqual(len(items), 2)
        first = items[0]
        self.assertEqual(first.source, "lse_share_chat")
        self.assertEqual(first.source_type, "community")
        self.assertEqual(first.document_type, "community_post")
        self.assertEqual(first.market, MARKET_UK)
        self.assertEqual(first.tickers, ("BP",))
        self.assertTrue(first.title)
        self.assertTrue(first.url)
        self.assertTrue(first.published_at)

    def test_collect_is_empty_stub(self) -> None:
        connector = LseShareChatConnector()
        request = CollectionRequest(
            tickers=("BP.",),
            start_date=date(2026, 2, 17),
            end_date=date(2026, 2, 17),
            markets={"BP.": "uk"},
        )
        items = connector.collect(request)
        self.assertEqual(items, [])
        self.assertEqual(connector.status, "stub")
        self.assertTrue(connector.last_errors)
        self.assertIn("403", connector.last_errors[0][1])

    def test_registry_registers_lse_share_chat(self) -> None:
        registry = create_default_registry()
        self.assertIsNotNone(registry.factory_for("lse_share_chat"))
        connector = registry.factory_for("lse_share_chat")()
        self.assertEqual(connector.name, "lse_share_chat")

    def test_community_soft_dedupe_uses_thread_id(self) -> None:
        published = "2026-02-17T08:39:00+00:00"
        first = {
            "source": "lse_share_chat",
            "source_type": "community",
            "external_id": "lse-share-chat-9022606",
            "ticker": "BP",
            "market": "uk",
            "title": "BP results chat",
            "published_at": published,
            "effective_at": published,
            "raw_metadata": {"thread_id": "9022606"},
        }
        second = {
            **first,
            "external_id": "lse-share-chat-9022606-dup",
        }
        self.assertEqual(dedupe_key(first), dedupe_key(second))
        self.assertEqual(
            dedupe_key(first),
            "uk:community:lse_share_chat:9022606",
        )
        annotated = annotate_feed_items([first, second])
        self.assertEqual(len(annotated), 2)
        self.assertEqual(annotated[0]["also_seen_on"], ["lse_share_chat"])
        self.assertEqual(
            annotated[0]["also_seen_on_labels"],
            ["LSE Share Chat (UK)"],
        )


if __name__ == "__main__":
    unittest.main()
