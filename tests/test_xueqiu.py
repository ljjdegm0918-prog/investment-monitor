"""Unit tests for Xueqiu CN/HK stub + fixture parser (no live network)."""

from __future__ import annotations

import json
import os
import unittest
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo
from unittest.mock import patch

from investment_monitor.dedupe import annotate_feed_items, dedupe_key
from investment_monitor.models import MARKET_CN, MARKET_HK, CollectionRequest
from investment_monitor.registry import create_default_registry
from investment_monitor.sources.xueqiu import (
    XueqiuConnector,
    parse_xueqiu_status_list,
)
from investment_monitor.web_repository import (
    normalize_cn_ticker,
    normalize_hk_ticker,
    normalize_xq_symbol,
)

CN_FIXTURE = (
    Path(__file__).resolve().parent
    / "fixtures"
    / "xueqiu"
    / "sh600519_board_2026-02-17.html"
)
HK_FIXTURE = (
    Path(__file__).resolve().parent
    / "fixtures"
    / "xueqiu"
    / "hk00700_board_2026-02-17.html"
)
SHANGHAI = ZoneInfo("Asia/Shanghai")
HONG_KONG = ZoneInfo("Asia/Hong_Kong")


class XueqiuSymbolNormalizeTests(unittest.TestCase):
    def test_normalize_cn_shanghai_forms(self) -> None:
        self.assertEqual(normalize_cn_ticker("600519"), "SH600519")
        self.assertEqual(normalize_cn_ticker("600519.SS"), "SH600519")
        self.assertEqual(normalize_cn_ticker("600519.SH"), "SH600519")
        self.assertEqual(normalize_cn_ticker("SH600519"), "SH600519")
        self.assertEqual(normalize_cn_ticker("sh600519"), "SH600519")

    def test_normalize_cn_shenzhen_forms(self) -> None:
        self.assertEqual(normalize_cn_ticker("000001"), "SZ000001")
        self.assertEqual(normalize_cn_ticker("000001.SZ"), "SZ000001")
        self.assertEqual(normalize_cn_ticker("SZ000001"), "SZ000001")
        self.assertEqual(normalize_cn_ticker("300750.SZ"), "SZ300750")

    def test_normalize_cn_preserves_unknown(self) -> None:
        self.assertEqual(normalize_cn_ticker("VOD"), "VOD")

    def test_normalize_hk_root_ticker(self) -> None:
        self.assertEqual(normalize_hk_ticker("0700"), "00700")
        self.assertEqual(normalize_hk_ticker("0700.HK"), "00700")
        self.assertEqual(normalize_hk_ticker("700"), "00700")

    def test_normalize_xq_symbol_by_market(self) -> None:
        self.assertEqual(
            normalize_xq_symbol("600519", market="cn"), "SH600519"
        )
        self.assertEqual(
            normalize_xq_symbol("0700", market="hk"), "HK00700"
        )
        self.assertEqual(
            normalize_xq_symbol("0700.HK", market="hk"), "HK00700"
        )
        self.assertEqual(
            normalize_xq_symbol("VOD", market="us"), "VOD"
        )


class XueqiuParserTests(unittest.TestCase):
    def test_parser_filters_shanghai_day(self) -> None:
        html = CN_FIXTURE.read_text(encoding="utf-8")
        rows = parse_xueqiu_status_list(
            html, on_date=date(2026, 2, 17), market="cn"
        )
        self.assertEqual(len(rows), 2)
        ids = {row.status_id for row in rows}
        self.assertEqual(ids, {"2345678901", "2345678902"})
        for row in rows:
            self.assertTrue(row.title)
            self.assertTrue(row.url.startswith("https://xueqiu.com/"))
            self.assertEqual(
                row.published_at.astimezone(SHANGHAI).date(),
                date(2026, 2, 17),
            )

    def test_parser_filters_hong_kong_day(self) -> None:
        html = HK_FIXTURE.read_text(encoding="utf-8")
        rows = parse_xueqiu_status_list(
            html, on_date=date(2026, 2, 17), market="hk"
        )
        self.assertEqual(len(rows), 2)
        ids = {row.status_id for row in rows}
        self.assertEqual(ids, {"3456789011", "3456789012"})
        for row in rows:
            self.assertEqual(
                row.published_at.astimezone(HONG_KONG).date(),
                date(2026, 2, 17),
            )

    def test_parser_empty_for_other_day(self) -> None:
        html = CN_FIXTURE.read_text(encoding="utf-8")
        rows = parse_xueqiu_status_list(
            html, on_date=date(2026, 2, 18), market="cn"
        )
        self.assertEqual(rows, [])

    def test_parser_rejects_unsupported_market(self) -> None:
        html = CN_FIXTURE.read_text(encoding="utf-8")
        with self.assertRaises(ValueError):
            parse_xueqiu_status_list(
                html, on_date=date(2026, 2, 17), market="us"
            )


class XueqiuConnectorTests(unittest.TestCase):
    def test_map_rows_builds_community_items_cn(self) -> None:
        html = CN_FIXTURE.read_text(encoding="utf-8")
        rows = parse_xueqiu_status_list(
            html, on_date=date(2026, 2, 17), market="cn"
        )
        connector = XueqiuConnector()
        items = connector.map_rows_for_tests(
            rows,
            ticker="600519",
            market="cn",
            collected_at=datetime(2026, 2, 17, 12, 0, tzinfo=SHANGHAI),
        )
        self.assertEqual(len(items), 2)
        first = items[0]
        self.assertEqual(first.source, "xueqiu")
        self.assertEqual(first.source_type, "community")
        self.assertEqual(first.document_type, "community_post")
        self.assertEqual(first.market, MARKET_CN)
        self.assertEqual(first.tickers, ("SH600519",))
        self.assertTrue(first.title)
        self.assertTrue(first.url)
        self.assertTrue(first.published_at)

    def test_map_rows_builds_community_items_hk(self) -> None:
        html = HK_FIXTURE.read_text(encoding="utf-8")
        rows = parse_xueqiu_status_list(
            html, on_date=date(2026, 2, 17), market="hk"
        )
        connector = XueqiuConnector()
        items = connector.map_rows_for_tests(
            rows,
            ticker="0700",
            market="hk",
            collected_at=datetime(2026, 2, 17, 12, 0, tzinfo=HONG_KONG),
        )
        self.assertEqual(len(items), 2)
        first = items[0]
        self.assertEqual(first.market, MARKET_HK)
        self.assertEqual(first.tickers, ("HK00700",))

    def test_collect_is_empty_stub_cn(self) -> None:
        connector = XueqiuConnector()
        request = CollectionRequest(
            tickers=("600519",),
            start_date=date(2026, 2, 17),
            end_date=date(2026, 2, 17),
            markets={"600519": "cn"},
        )
        items = connector.collect(request)
        self.assertEqual(items, [])
        self.assertEqual(connector.status, "stub")
        self.assertTrue(connector.last_errors)
        self.assertIn("400016", connector.last_errors[0][1])

    def test_collect_is_empty_stub_hk(self) -> None:
        connector = XueqiuConnector()
        request = CollectionRequest(
            tickers=("0700.HK",),
            start_date=date(2026, 2, 17),
            end_date=date(2026, 2, 17),
            markets={"0700.HK": "hk"},
        )
        items = connector.collect(request)
        self.assertEqual(items, [])
        self.assertTrue(connector.last_errors)
        self.assertIn("HK00700", connector.last_errors[0][0])

    def test_collect_skips_other_markets(self) -> None:
        connector = XueqiuConnector()
        request = CollectionRequest(
            tickers=("BHP.AX",),
            start_date=date(2026, 2, 17),
            end_date=date(2026, 2, 17),
            markets={"BHP.AX": "au"},
        )
        items = connector.collect(request)
        self.assertEqual(items, [])
        self.assertEqual(connector.last_errors, ())

    def test_registry_registers_xueqiu(self) -> None:
        registry = create_default_registry()
        self.assertIsNotNone(registry.factory_for("xueqiu"))
        connector = registry.factory_for("xueqiu")()
        self.assertEqual(connector.name, "xueqiu")

    def test_community_soft_dedupe_uses_status_id(self) -> None:
        published = "2026-02-17T02:39:00+00:00"
        first = {
            "source": "xueqiu",
            "source_type": "community",
            "external_id": "xueqiu-2345678901",
            "ticker": "SH600519",
            "market": "cn",
            "title": "茅台三季报简评",
            "published_at": published,
            "effective_at": published,
            "raw_metadata": {"status_id": "2345678901"},
        }
        second = {
            **first,
            "external_id": "xueqiu-2345678901-dup",
        }
        self.assertEqual(dedupe_key(first), dedupe_key(second))
        self.assertEqual(
            dedupe_key(first),
            "cn:community:xueqiu:2345678901",
        )
        annotated = annotate_feed_items([first, second])
        self.assertEqual(len(annotated), 2)
        self.assertEqual(annotated[0]["also_seen_on"], ["xueqiu"])
        self.assertEqual(
            annotated[0]["also_seen_on_labels"],
            ["Xueqiu (CN/HK)"],
        )

    @patch.dict(os.environ, {"XUEQIU_COOKIE": "xq_a_token=fake_token_for_testing"})
    def test_collect_live_via_cookie(self) -> None:
        """When XUEQIU_COOKIE is set, collect should attempt the JSON API path.

        Because the real API is not reachable from this sandbox, we mock the
        response and verify the live path is entered (items returned, status
        reflects cookie-enabled mode) rather than staying purely in stub.
        """
        connector = XueqiuConnector()
        # Mock _fetch_via_cookie to return empty list (cookie set, no posts)
        with patch.object(
            connector, "_fetch_via_cookie", return_value=[]
        ):
            request = CollectionRequest(
                tickers=("600519",),
                start_date=date(2026, 2, 17),
                end_date=date(2026, 2, 17),
                markets={"600519": "cn"},
            )
            items = connector.collect(request)
            # When cookie is set and _fetch_via_cookie returns [] (not None),
            # the live path is taken and items (empty list) are returned.
            self.assertEqual(items, [])
            # Status should reflect the live/cookie-enabled state,
            # not pure stub.
            self.assertIn("LIVE", connector.status)

    @patch.dict(os.environ, {"XUEQIU_COOKIE": "xq_a_token=invalid_token"})
    def test_collect_cookie_rejected_falls_to_stub(self) -> None:
        """When XUEQIU_COOKIE has invalid token, _fetch_via_cookie returns None
        and the connector falls back to honest stub."""
        connector = XueqiuConnector()
        # Mock _fetch_via_cookie to return None (simulates 400016 token rejection)
        with patch.object(
            connector, "_fetch_via_cookie", return_value=None
        ):
            request = CollectionRequest(
                tickers=("600519",),
                start_date=date(2026, 2, 17),
                end_date=date(2026, 2, 17),
                markets={"600519": "cn"},
            )
            items = connector.collect(request)
            # When _fetch_via_cookie returns None, stub path is taken.
            self.assertEqual(items, [])
            # Status should be pure stub.
            self.assertEqual(connector.status, "stub")
