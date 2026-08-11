"""Unit tests for stockhead_au connector + parser (no live network)."""

from __future__ import annotations

import unittest
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from investment_monitor.models import MARKET_AU, CollectionRequest
from investment_monitor.registry import create_default_registry
from investment_monitor.sources.stockhead_au import (
    StockheadAuConnector,
    parse_stockhead_search_rss,
)
from investment_monitor.web_repository import normalize_au_ticker

FIXTURE = (
    Path(__file__).resolve().parent
    / "fixtures"
    / "stockhead"
    / "bhp_search_2026-08-11.xml"
)
SYDNEY = ZoneInfo("Australia/Sydney")


class StockheadParserTests(unittest.TestCase):
    """parser.py 单元测试（不访问网络）。"""

    def test_parser_filters_by_ticker_and_sydney_day(self) -> None:
        """2026-08-11 UTC 日期 + BHP ticker 应命中2条。"""
        xml = FIXTURE.read_text(encoding="utf-8")
        rows = parse_stockhead_search_rss(
            xml, ticker="BHP", on_date=date(2026, 8, 11)
        )
        self.assertEqual(len(rows), 2)
        slugs = {row.article_slug for row in rows}
        self.assertIn("bhp-flags-major-copper-expansion-at-olympic-dam", slugs)
        self.assertIn(
            "asx-iron-ore-roundup-bhp-and-rio-dip-on-china-demand-concerns", slugs
        )

    def test_parser_excludes_other_date(self) -> None:
        """2026-08-10 只有一篇 BHP 文章，2026-08-12 无文章。"""
        xml = FIXTURE.read_text(encoding="utf-8")
        rows_10 = parse_stockhead_search_rss(
            xml, ticker="BHP", on_date=date(2026, 8, 10)
        )
        self.assertEqual(len(rows_10), 1)
        self.assertEqual(
            rows_10[0].article_slug,
            "bhp-quarterly-production-update-record-copper-output",
        )
        rows_12 = parse_stockhead_search_rss(
            xml, ticker="BHP", on_date=date(2026, 8, 12)
        )
        self.assertEqual(rows_12, [])

    def test_parser_excludes_wrong_ticker(self) -> None:
        """2026-08-11 搜 RIO 时，只有1条纯 RIO 文章（BHP+RIO 双标签那条也匹配 RIO）。"""
        xml = FIXTURE.read_text(encoding="utf-8")
        rows = parse_stockhead_search_rss(
            xml, ticker="RIO", on_date=date(2026, 8, 11)
        )
        # 条目2 有 BHP+RIO 双标签，条目4 只有 RIO → 共2条
        self.assertEqual(len(rows), 2)
        slugs = {row.article_slug for row in rows}
        self.assertIn("rio-tinto-surges-on-dividend-announcement", slugs)
        self.assertIn(
            "asx-iron-ore-roundup-bhp-and-rio-dip-on-china-demand-concerns", slugs
        )

    def test_parser_row_fields(self) -> None:
        """行字段校验：title、url、published_at、summary。"""
        xml = FIXTURE.read_text(encoding="utf-8")
        rows = parse_stockhead_search_rss(
            xml, ticker="BHP", on_date=date(2026, 8, 11)
        )
        for row in rows:
            self.assertTrue(row.title, "title 不应为空")
            self.assertTrue(row.url.startswith("https://stockhead.com.au/"))
            self.assertEqual(
                row.published_at.astimezone(SYDNEY).date(), date(2026, 8, 11)
            )
            self.assertTrue(row.article_slug)

    def test_parser_normalizes_ticker(self) -> None:
        """ticker 大小写不敏感：'bhp.ax' 应与 'BHP' 等效。"""
        xml = FIXTURE.read_text(encoding="utf-8")
        rows_upper = parse_stockhead_search_rss(
            xml, ticker="BHP", on_date=date(2026, 8, 11)
        )
        rows_lower = parse_stockhead_search_rss(
            xml, ticker="bhp", on_date=date(2026, 8, 11)
        )
        self.assertEqual(len(rows_upper), len(rows_lower))

    def test_parser_empty_for_malformed_xml(self) -> None:
        """损坏的 XML 应返回空列表而不是抛出异常。"""
        rows = parse_stockhead_search_rss(
            "<bad xml>>>", ticker="BHP", on_date=date(2026, 8, 11)
        )
        self.assertEqual(rows, [])


class StockheadConnectorTests(unittest.TestCase):
    """connector.py 单元测试（用 fixture 注入替代真实网络）。"""

    def _make_connector(self) -> StockheadAuConnector:
        """创建一个用 fixture XML 替代网络抓取的连接器。"""
        xml = FIXTURE.read_text(encoding="utf-8")
        return StockheadAuConnector(fetch_xml=lambda ticker: xml)

    def test_collect_returns_items_for_au_ticker(self) -> None:
        """collect() 应为 AU ticker 的2026-08-11 返回2条 BHP 条目。"""
        connector = self._make_connector()
        request = CollectionRequest(
            tickers=("BHP",),
            start_date=date(2026, 8, 11),
            end_date=date(2026, 8, 11),
            markets={"BHP": "au"},
        )
        items = connector.collect(request)
        self.assertEqual(len(items), 2)
        for item in items:
            self.assertEqual(item.source, "stockhead_au")
            self.assertEqual(item.source_type, "community")
            self.assertEqual(item.document_type, "community_post")
            self.assertEqual(item.market, MARKET_AU)
            self.assertEqual(item.tickers, ("BHP",))
            self.assertTrue(item.title)
            self.assertTrue(item.url.startswith("https://stockhead.com.au/"))
            self.assertTrue(
                item.external_id.startswith("stockhead-"),
                f"external_id 应以 'stockhead-' 开头，实际: {item.external_id!r}",
            )

    def test_collect_skips_non_au_market(self) -> None:
        """非 AU 市场的 ticker 应被跳过，返回空列表。"""
        connector = self._make_connector()
        request = CollectionRequest(
            tickers=("BHP",),
            start_date=date(2026, 8, 11),
            end_date=date(2026, 8, 11),
            markets={"BHP": "us"},
        )
        items = connector.collect(request)
        self.assertEqual(items, [])

    def test_collect_date_range(self) -> None:
        """跨日期范围：2026-08-10 到 11 应返回3条（10日1条+11日2条）。"""
        connector = self._make_connector()
        request = CollectionRequest(
            tickers=("BHP",),
            start_date=date(2026, 8, 10),
            end_date=date(2026, 8, 11),
            markets={"BHP": "au"},
        )
        items = connector.collect(request)
        self.assertEqual(len(items), 3)
        days = {item.published_at.astimezone(SYDNEY).date() for item in items}
        self.assertIn(date(2026, 8, 10), days)
        self.assertIn(date(2026, 8, 11), days)

    def test_connector_status_live(self) -> None:
        """status 属性应为 'live'。"""
        connector = StockheadAuConnector()
        self.assertEqual(connector.status, "live")

    def test_map_rows_builds_items(self) -> None:
        """map_rows() 应从 fixture rows 构建正确的 InformationItem 列表。"""
        xml = FIXTURE.read_text(encoding="utf-8")
        rows = parse_stockhead_search_rss(
            xml, ticker="BHP", on_date=date(2026, 8, 11)
        )
        connector = StockheadAuConnector()
        collected_at = datetime(2026, 8, 11, 12, 0, tzinfo=SYDNEY)
        items = connector.map_rows(rows, ticker="BHP.AX", collected_at=collected_at)
        self.assertEqual(len(items), 2)
        self.assertEqual(items[0].tickers, ("BHP",))
        self.assertEqual(items[0].issuer, "BHP")
        self.assertIsNotNone(items[0].effective_at)

    def test_registry_registers_stockhead_au(self) -> None:
        """stockhead_au 应在 registry 中注册。"""
        registry = create_default_registry()
        self.assertIsNotNone(registry.factory_for("stockhead_au"))
        connector = registry.factory_for("stockhead_au")()
        self.assertEqual(connector.name, "stockhead_au")
        self.assertEqual(connector.status, "live")


if __name__ == "__main__":
    unittest.main()
