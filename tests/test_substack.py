"""Unit tests for Substack LIVE publication-whitelist connector (no live network).

Mirrors ``tests/test_seeking_alpha.py``: New York calendar-day filter,
injected fetch (default suite never hits the network), and registry
registration. Honesty (spike 2026-08-11, ``tests/fixtures/substack/SPIKE.md``):
Substack is an author newsletter platform, NOT a ticker forum; ticker binding
is whitelist + client-side keyword matching with false-positive/negative
caveats — the tests pin the default whitelist and the keyword-match caveat
(``Apple`` does not match ticker ``AAPL``).
"""

from __future__ import annotations

import unittest
from datetime import date, datetime
from pathlib import Path

from investment_monitor.dedupe import annotate_feed_items, dedupe_key
from investment_monitor.models import MARKET_US, CollectionRequest
from investment_monitor.registry import create_default_registry
from investment_monitor.sources.substack.connector import DEFAULT_PUBLICATIONS
from investment_monitor.sources.substack import (
    SubstackConnector,
    SubstackFeedRow,
    SubstackRequestError,
    new_york_day,
    parse_substack_rss,
)

FIXTURE_NOAHPINION = (
    Path(__file__).resolve().parent
    / "fixtures"
    / "substack"
    / "noahpinion_2026-08-11.xml"
)
FIXTURE_NOTBORING = (
    Path(__file__).resolve().parent
    / "fixtures"
    / "substack"
    / "notboring_2026-08-11.xml"
)


class SubstackTests(unittest.TestCase):
    def test_new_york_day(self) -> None:
        # 2026-08 是 EDT (UTC-4)：UTC 正午 → 纽约当天上午。
        self.assertEqual(
            new_york_day(datetime.fromisoformat("2026-08-11T08:01:13+00:00")),
            date(2026, 8, 11),
        )
        # UTC 已跨到 8-12 凌晨，但纽约还是 8-11 晚上（EDT 22:45）。
        self.assertEqual(
            new_york_day(datetime.fromisoformat("2026-08-12T02:45:00+00:00")),
            date(2026, 8, 11),
        )
        # 纽约午夜前（EDT 19:30）。
        self.assertEqual(
            new_york_day(datetime.fromisoformat("2026-08-11T23:30:00+00:00")),
            date(2026, 8, 11),
        )
        # 纽约已进入新的一天（EDT 00:30）。
        self.assertEqual(
            new_york_day(datetime.fromisoformat("2026-08-12T04:30:00+00:00")),
            date(2026, 8, 12),
        )

    def test_parser_filters_new_york_day(self) -> None:
        xml_text = FIXTURE_NOAHPINION.read_text(encoding="utf-8")
        rows = parse_substack_rss(xml_text, on_date=date(2026, 8, 11))
        self.assertEqual(len(rows), 3)
        ids = {row.post_id for row in rows}
        self.assertEqual(
            ids,
            {
                "https://www.noahpinion.blog/p/the-poverty-of-anti-tech-thought",
                "https://www.noahpinion.blog/p/nvda-capex-cycle-keeps-rolling",
                "https://www.noahpinion.blog/p/apple-and-the-ai-handset",
            },
        )
        for row in rows:
            self.assertTrue(row.title)
            self.assertTrue(row.url)
            self.assertEqual(new_york_day(row.published_at), date(2026, 8, 11))

    def test_parser_empty_for_other_day(self) -> None:
        xml_text = FIXTURE_NOAHPINION.read_text(encoding="utf-8")
        # 跨 UTC 日边界的条目按纽约日属于 08-11，因此 08-12 无条目。
        self.assertEqual(
            parse_substack_rss(xml_text, on_date=date(2026, 8, 12)),
            [],
        )
        self.assertEqual(
            parse_substack_rss(xml_text, on_date=date(2026, 8, 9)),
            [],
        )

    def test_collect_uses_injected_fetch(self) -> None:
        xml_text = FIXTURE_NOAHPINION.read_text(encoding="utf-8")
        connector = SubstackConnector(
            publications=("noahpinion.blog",),
            fetch_rss=lambda _publication: xml_text,
        )
        request = CollectionRequest(
            tickers=("NVDA",),
            start_date=date(2026, 8, 11),
            end_date=date(2026, 8, 11),
            markets={"NVDA": "us"},
        )
        items = connector.collect(request)
        self.assertEqual(len(items), 1)
        self.assertEqual(connector.status, "live")
        first = items[0]
        self.assertEqual(first.source, "substack")
        self.assertEqual(first.source_type, "community")
        self.assertEqual(first.document_type, "community_post")
        self.assertEqual(first.market, MARKET_US)
        self.assertEqual(first.tickers, ("NVDA",))
        self.assertEqual(first.issuer, "noahpinion.blog")
        self.assertEqual(
            first.external_id,
            "substack-https://www.noahpinion.blog/p/nvda-capex-cycle-keeps-rolling",
        )
        self.assertEqual(
            first.raw_metadata.get("category"), "newsletter_article"
        )
        self.assertEqual(
            first.raw_metadata.get("publication"), "noahpinion.blog"
        )
        self.assertEqual(first.raw_metadata.get("ny_day"), "2026-08-11")
        self.assertEqual(first.raw_metadata.get("keyword_matched"), True)

    def test_keyword_match_is_best_effort(self) -> None:
        # SPIKE 诚实性：无结构化 ticker 绑定。标题/摘要含 "Apple" 的公司名
        # 提及不匹配 ticker "AAPL"（关键字 substring 匹配的假阴性）。
        xml_text = FIXTURE_NOAHPINION.read_text(encoding="utf-8")
        connector = SubstackConnector(
            publications=("noahpinion.blog",),
            fetch_rss=lambda _publication: xml_text,
        )
        request = CollectionRequest(
            tickers=("AAPL",),
            start_date=date(2026, 8, 11),
            end_date=date(2026, 8, 11),
            markets={"AAPL": "us"},
        )
        items = connector.collect(request)
        self.assertEqual(items, [])
        self.assertEqual(connector.last_errors, ())

    def test_collect_skips_non_us_tickers(self) -> None:
        # Substack 是 US-only 源：非 US ticker 即使关键字命中也不产出条目。
        xml_text = FIXTURE_NOAHPINION.read_text(encoding="utf-8")
        connector = SubstackConnector(
            publications=("noahpinion.blog",),
            fetch_rss=lambda _publication: xml_text,
        )
        request = CollectionRequest(
            tickers=("VOD",),
            start_date=date(2026, 8, 11),
            end_date=date(2026, 8, 11),
            markets={"VOD": "uk"},
        )
        items = connector.collect(request)
        self.assertEqual(items, [])
        self.assertEqual(connector.last_errors, ())

    def test_keyword_match_case_insensitive_and_summary(self) -> None:
        # 匹配对大小写不敏感，且同时查标题与摘要（notboring 条目在摘要中
        # 提及 TSMC，关键词 "TSMC" 应命中）。
        row = SubstackFeedRow(
            post_id="https://www.notboring.co/p/weekly-dose-of-optimism-207",
            title="Weekly Dose of Optimism #207",
            url="https://www.notboring.co/p/weekly-dose-of-optimism-207",
            published_at=datetime.fromisoformat("2026-08-11T12:50:11+00:00"),
            summary="TSMC keeps raising its capital expenditure guidance.",
        )
        # 匹配大小写不敏感；返回的是传入的 ticker 原样（调用方 CollectionRequest
        # 会先 normalize 为大写）。
        self.assertEqual(
            SubstackConnector._match_tickers(row, ("TSMC",)), ("TSMC",)
        )
        self.assertEqual(
            SubstackConnector._match_tickers(row, ("tsmc",)), ("tsmc",)
        )
        # 未提供 tickers 时不产生关键字过滤（whitelist 模式）。
        self.assertEqual(SubstackConnector._match_tickers(row, ()), ())
        # 不匹配的 ticker 被跳过。
        self.assertEqual(SubstackConnector._match_tickers(row, ("NVDA",)), ())

    def test_collect_publication_failure_records_and_continues(self) -> None:
        # 单个刊物 feed 失败只记录 last_errors，不中断其余白名单刊物。
        noah = FIXTURE_NOAHPINION.read_text(encoding="utf-8")
        notboring = FIXTURE_NOTBORING.read_text(encoding="utf-8")

        def fetch(publication: str) -> str:
            if publication == "noahpinion.blog":
                raise SubstackRequestError(
                    "substack feed HTTP 404 for noahpinion.blog"
                )
            return notboring

        connector = SubstackConnector(
            publications=("noahpinion.blog", "notboring.co"),
            fetch_rss=fetch,
        )
        request = CollectionRequest(
            tickers=("TSMC",),
            start_date=date(2026, 8, 11),
            end_date=date(2026, 8, 11),
            markets={"TSMC": "us"},
        )
        items = connector.collect(request)
        # 只有 notboring.co 的条目通过关键词过滤（摘要含 TSMC）。
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0].issuer, "notboring.co")
        self.assertEqual(
            connector.last_errors,
            (("noahpinion.blog", "substack feed HTTP 404 for noahpinion.blog"),),
        )

    def test_default_whitelist_honesty(self) -> None:
        # SPIKE 诚实性：白名单只含活跃刊物。thediff 已迁移到自建域
        # thediff.co（urllib-only 下 SSL 校验失败），
        # yellowbrickinvesting 是 waitlist 页 —— 都不在白名单里。
        self.assertEqual(
            DEFAULT_PUBLICATIONS,
            (
                "noahpinion.blog",
                "notboring.co",
                "astralcodexten.com",
                "paulkrugman.substack.com",
                "oneusefulthing.org",
            ),
        )
        self.assertNotIn("thediff.substack.com", DEFAULT_PUBLICATIONS)
        self.assertNotIn(
            "yellowbrickinvesting.substack.com", DEFAULT_PUBLICATIONS
        )

    def test_registry_registers_substack(self) -> None:
        registry = create_default_registry()
        self.assertIsNotNone(registry.factory_for("substack"))
        connector = registry.factory_for("substack")()
        self.assertEqual(connector.name, "substack")
        self.assertEqual(connector.status, "live")

    def test_community_soft_dedupe_source_scoped_title(self) -> None:
        # 软去重：substack 社区行使用 source-scoped 标题 fallback
        # （ticker + 纽约日 + 归一化标题），绝不与未来第二个 US 社区源按
        # 标题交叉配对；相同 post 的两行得到相同 key 并互相标注。
        published = "2026-08-11T08:01:13+00:00"
        first = {
            "source": "substack",
            "source_type": "community",
            "external_id": (
                "substack-https://www.noahpinion.blog/p/"
                "the-poverty-of-anti-tech-thought"
            ),
            "ticker": "NVDA",
            "market": "us",
            "title": "The poverty of anti-tech thought",
            "published_at": published,
            "effective_at": published,
            "raw_metadata": {"publication": "noahpinion.blog"},
        }
        second = {
            **first,
            "external_id": (
                "substack-https://www.noahpinion.blog/p/"
                "the-poverty-of-anti-tech-thought-dup"
            ),
        }
        key = (
            "us:community:title:substack:NVDA:2026-08-11:"
            "the poverty of anti-tech thought"
        )
        self.assertEqual(dedupe_key(first), dedupe_key(second))
        self.assertEqual(dedupe_key(first), key)
        annotated = annotate_feed_items([first, second])
        self.assertEqual(len(annotated), 2)
        self.assertEqual(annotated[0]["also_seen_on"], ["substack"])


if __name__ == "__main__":
    unittest.main()
