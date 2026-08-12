import json
from datetime import date, datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Tuple
import unittest

from investment_monitor.application import ConfiguredCollectionResult
from investment_monitor.models import InformationItem
from investment_monitor.repository import SaveResult
from investment_monitor.sqlite_repository import SQLiteInformationRepository
from investment_monitor.web import (
    WebApplication,
    _daily_company_sort_key,
    _daily_item_category,
    _daily_item_date,
    _shanghai_default_day,
)
from investment_monitor.web_repository import FeedFilters, WebRepository

# 2026-08-12T16:30Z 在上海是 2026-08-13 00:30，在纽约仍是 2026-08-12 12:30。
FIXED_NOW = datetime(2026, 8, 12, 16, 30, tzinfo=timezone.utc)


class FakeResolver:
    def resolve(self, ticker: str):
        records = {
            "AAPL": {
                "ticker": "AAPL",
                "name": "Apple Inc.",
                "exchange": "Nasdaq",
                "cik": "0000320193",
                "mapping_status": "mapped",
            },
            "MSFT": {
                "ticker": "MSFT",
                "name": "Microsoft Corporation",
                "exchange": "Nasdaq",
                "cik": "0000789019",
                "mapping_status": "mapped",
            },
            "AAA": {
                "ticker": "AAA",
                "name": "Zebra Corp",
                "exchange": "NYSE",
                "cik": "",
                "mapping_status": "mapped",
            },
            "ZZZ": {
                "ticker": "ZZZ",
                "name": "Apple Corp",
                "exchange": "NYSE",
                "cik": "",
                "mapping_status": "mapped",
            },
        }
        return records.get(ticker)


def make_item(
    external_id: str,
    *,
    ticker: str = "AAPL",
    tickers: Tuple[str, ...] = None,
    source: str = "sec",
    source_type: str = "",
    title: str = "",
    published_at: datetime = None,
    collected_at: datetime = None,
    effective_at: datetime = None,
    accepted_at: str = None,
    calendar_date: str = None,
    market: str = "us",
    form: str = "8-K",
) -> InformationItem:
    metadata = {"generated": False}
    if accepted_at is not None:
        metadata["acceptanceDateTime"] = accepted_at
    if calendar_date is not None:
        metadata["calendar_date"] = calendar_date
    return InformationItem(
        source=source,
        source_type=source_type or (
            "regulatory_filing" if source == "sec" else "news"
        ),
        external_id=external_id,
        tickers=tickers or (ticker,),
        issuer="Apple Inc." if ticker == "AAPL" else "Microsoft Corporation",
        published_at=published_at or datetime(2026, 8, 10, tzinfo=timezone.utc),
        title=title or f"{form} for {ticker}",
        document_type=form,
        url=f"https://example.test/{external_id}",
        collected_at=collected_at or datetime(2026, 8, 10, 12, tzinfo=timezone.utc),
        raw_metadata=metadata,
        market=market,
        effective_at=effective_at,
    )


class DailyReportHelperTests(unittest.TestCase):
    def test_category_mapping(self) -> None:
        self.assertEqual(_daily_item_category("regulatory_filing"), "filings")
        self.assertEqual(_daily_item_category("regulatory_disclosure"), "filings")
        self.assertEqual(_daily_item_category("news"), "news")
        self.assertEqual(_daily_item_category("community"), "community")
        self.assertIsNone(_daily_item_category("research"))

    def test_company_sort_key_orders_name_then_ticker_then_market(self) -> None:
        groups = [
            {"name": "Zebra Corp", "ticker": "AAA", "market": "us"},
            {"name": "apple inc", "ticker": "BBB", "market": "us"},
            {"name": "apple inc", "ticker": "AAA", "market": "tw"},
            {"name": "apple inc", "ticker": "AAA", "market": "us"},
        ]
        ordered = sorted(groups, key=_daily_company_sort_key)
        self.assertEqual(
            [(g["name"], g["ticker"], g["market"]) for g in ordered],
            [
                ("apple inc", "AAA", "tw"),
                ("apple inc", "AAA", "us"),
                ("apple inc", "BBB", "us"),
                ("Zebra Corp", "AAA", "us"),
            ],
        )

    def test_report_day_prefers_calendar_date(self) -> None:
        item = {
            "raw_metadata": {"calendar_date": "2026-08-10"},
            "effective_at": "2026-08-10T16:30:00+00:00",
        }
        self.assertEqual(_daily_item_date(item), date(2026, 8, 10))

    def test_report_day_uses_shanghai_for_effective_time(self) -> None:
        before = {"raw_metadata": {}, "effective_at": "2026-08-10T15:59:59+00:00"}
        after = {"raw_metadata": {}, "effective_at": "2026-08-10T16:00:00+00:00"}
        self.assertEqual(_daily_item_date(before), date(2026, 8, 10))
        self.assertEqual(_daily_item_date(after), date(2026, 8, 11))


class _DailyRangeHarness(unittest.TestCase):
    clock = None  # 子类可覆盖为返回固定时间的 callable，用于测试默认日期。
    enabled_sources = ("sec", "news", "community")  # 子类可覆盖。

    def setUp(self) -> None:
        self.temporary_directory = TemporaryDirectory()
        self.project_root = Path(self.temporary_directory.name)
        (self.project_root / "config").mkdir()
        (self.project_root / "data").mkdir()
        source_lines = "".join(f"  - {name}\n" for name in self.enabled_sources)
        (self.project_root / "config" / "settings.yaml").write_text(
            f"enabled_sources:\n{source_lines}database_path: ../data/web.sqlite3\n",
            encoding="utf-8",
        )
        (self.project_root / "config" / "universe.csv").write_text(
            "ticker,list_type\nAAPL,holdings\n", encoding="utf-8"
        )
        cache_directory = self.project_root / ".cache" / "investment_monitor"
        cache_directory.mkdir(parents=True)
        (cache_directory / "company_tickers.json").write_text(json.dumps({
            "0": {"cik_str": 320193, "ticker": "AAPL", "title": "Apple Inc."},
            "1": {"cik_str": 789019, "ticker": "MSFT", "title": "Microsoft Corporation"},
        }), encoding="utf-8")
        self.items = SQLiteInformationRepository(
            self.project_root / "data" / "web.sqlite3"
        )
        self.application = WebApplication(
            self.project_root,
            collection_runner=self.noop_collection_runner,
            clock=self.clock,
        )

    def tearDown(self) -> None:
        self.temporary_directory.cleanup()

    def noop_collection_runner(self, **kwargs):
        return ConfiguredCollectionResult(
            items=(),
            failures=(),
            save_result=SaveResult(),
            database_path=self.project_root / "data" / "web.sqlite3",
            stored_count=self.items.count(),
        )

    def payload(self, response):
        return json.loads(response.body.decode("utf-8"))

    def report(self, start: str, end: str):
        response = self.application.handle(
            "GET", f"/api/daily-range?start_date={start}&end_date={end}"
        )
        self.assertEqual(response.status, 200)
        return self.payload(response)


class DailyRangeApiTests(_DailyRangeHarness):
    def test_single_day_range(self) -> None:
        self.items.save([make_item("one", published_at=datetime(2026, 8, 10, 4, tzinfo=timezone.utc))])
        payload = self.report("2026-08-10", "2026-08-10")
        self.assertEqual([d["date"] for d in payload["days"]], ["2026-08-10"])
        self.assertEqual(payload["days"][0]["item_count"], 1)

    def test_multi_day_range_includes_both_endpoints_newest_first(self) -> None:
        self.items.save([
            make_item("day-10", published_at=datetime(2026, 8, 10, 4, tzinfo=timezone.utc)),
            make_item("day-12", published_at=datetime(2026, 8, 12, 4, tzinfo=timezone.utc)),
        ])
        payload = self.report("2026-08-10", "2026-08-12")
        self.assertEqual(
            [d["date"] for d in payload["days"]],
            ["2026-08-12", "2026-08-11", "2026-08-10"],
        )
        self.assertEqual(payload["days"][0]["item_count"], 1)
        self.assertEqual(payload["days"][2]["item_count"], 1)
        self.assertEqual(payload["days"][1]["item_count"], 0)

    def test_empty_day_still_returns_section(self) -> None:
        self.items.save([make_item("day-10", published_at=datetime(2026, 8, 10, 4, tzinfo=timezone.utc))])
        payload = self.report("2026-08-10", "2026-08-12")
        empty = payload["days"][1]
        self.assertEqual(empty["date"], "2026-08-11")
        self.assertEqual(empty["item_count"], 0)
        self.assertEqual(empty["company_count"], 0)
        self.assertEqual(empty["companies"], [])

    def test_companies_sorted_by_name_not_ticker(self) -> None:
        # name 与 ticker 冲突：Zebra Corp 的 ticker(AAA) 更靠前，
        # Apple Corp 的 ticker(ZZZ) 更靠后。按 name 优先时 Apple Corp 应在前。
        resolver = FakeResolver()
        self.application.repository.add_companies_batch(
            "AAA ZZZ", ("holdings",), resolver  # type: ignore[arg-type]
        )
        self.items.save([
            make_item("aaa-1", ticker="AAA", published_at=datetime(2026, 8, 10, 4, tzinfo=timezone.utc)),
            make_item("zzz-1", ticker="ZZZ", published_at=datetime(2026, 8, 10, 5, tzinfo=timezone.utc)),
        ])
        payload = self.report("2026-08-10", "2026-08-10")
        companies = payload["days"][0]["companies"]
        self.assertEqual(
            [(c["name"], c["ticker"]) for c in companies],
            [("Apple Corp", "ZZZ"), ("Zebra Corp", "AAA")],
        )

    def test_filing_news_community_grouped_and_ordered(self) -> None:
        self.items.save([
            make_item("filing-1", source="sec", source_type="regulatory_filing",
                      published_at=datetime(2026, 8, 10, 5, tzinfo=timezone.utc)),
            make_item("news-1", source="news", source_type="news",
                      published_at=datetime(2026, 8, 10, 6, tzinfo=timezone.utc)),
            make_item("community-1", source="community", source_type="community",
                      published_at=datetime(2026, 8, 10, 7, tzinfo=timezone.utc)),
        ])
        payload = self.report("2026-08-10", "2026-08-10")
        day = payload["days"][0]
        company = day["companies"][0]
        self.assertEqual(day["counts"], {"filings": 1, "news": 1, "community": 1})
        self.assertEqual(
            [i["type"] for i in company["items"]],
            ["Filing", "News", "Community"],
        )
        self.assertEqual(day["item_count"], 3)
        self.assertEqual(day["company_count"], 1)

    def test_same_company_items_land_in_their_own_days(self) -> None:
        self.items.save([
            make_item("day-10", published_at=datetime(2026, 8, 10, 4, tzinfo=timezone.utc)),
            make_item("day-12", published_at=datetime(2026, 8, 12, 4, tzinfo=timezone.utc)),
        ])
        payload = self.report("2026-08-10", "2026-08-12")
        self.assertEqual(
            [i["title"] for i in payload["days"][0]["companies"][0]["items"]],
            ["8-K for AAPL"],
        )
        self.assertEqual(
            [i["title"] for i in payload["days"][2]["companies"][0]["items"]],
            ["8-K for AAPL"],
        )

    def test_collected_at_does_not_determine_report_day(self) -> None:
        self.items.save([make_item(
            "news-1", source="news", source_type="news",
            published_at=datetime(2026, 8, 10, 4, tzinfo=timezone.utc),
            collected_at=datetime(2026, 8, 12, 4, tzinfo=timezone.utc),
        )])
        self.assertEqual(self.report("2026-08-10", "2026-08-10")["days"][0]["item_count"], 1)
        self.assertEqual(self.report("2026-08-12", "2026-08-12")["days"][0]["item_count"], 0)

    def test_effective_at_priority_over_published_at(self) -> None:
        self.items.save([make_item(
            "eff-1",
            published_at=datetime(2026, 8, 10, 2, tzinfo=timezone.utc),
            effective_at=datetime(2026, 8, 10, 20, tzinfo=timezone.utc),
        )])
        # 2026-08-10T20:00Z is 2026-08-11 in Shanghai.
        self.assertEqual(self.report("2026-08-11", "2026-08-11")["days"][0]["item_count"], 1)
        self.assertEqual(self.report("2026-08-10", "2026-08-10")["days"][0]["item_count"], 0)

    def test_sec_acceptance_datetime_fallback(self) -> None:
        self.items.save([make_item(
            "sec-1",
            accepted_at="2026-08-10T16:30:00Z",
            published_at=datetime(2026, 8, 10, 0, tzinfo=timezone.utc),
        )])
        self.assertEqual(self.report("2026-08-11", "2026-08-11")["days"][0]["item_count"], 1)

    def test_non_sec_news_uses_canonical_published_time(self) -> None:
        self.items.save([make_item(
            "tw-news-1", source="news", source_type="news",
            published_at=datetime(2026, 8, 10, 18, tzinfo=timezone.utc),
        )])
        # 18:00 UTC is 2026-08-11 02:00 in Shanghai.
        self.assertEqual(self.report("2026-08-11", "2026-08-11")["days"][0]["item_count"], 1)

    def test_date_only_calendar_date_not_shifted(self) -> None:
        self.items.save([make_item(
            "date-only", calendar_date="2026-08-10",
            published_at=datetime(2026, 8, 10, 16, 30, tzinfo=timezone.utc),
        )])
        # published_at would land on 2026-08-11 in Shanghai, but calendar_date wins.
        self.assertEqual(self.report("2026-08-10", "2026-08-10")["days"][0]["item_count"], 1)
        self.assertEqual(self.report("2026-08-11", "2026-08-11")["days"][0]["item_count"], 0)

    def test_late_data_on_end_date_not_dropped(self) -> None:
        self.items.save([make_item(
            "late-1", published_at=datetime(2026, 8, 12, 15, 59, 59, tzinfo=timezone.utc),
        )])
        payload = self.report("2026-08-12", "2026-08-12")
        self.assertEqual(payload["days"][0]["item_count"], 1)

    def test_start_after_end_returns_400(self) -> None:
        response = self.application.handle(
            "GET", "/api/daily-range?start_date=2026-08-12&end_date=2026-08-10"
        )
        self.assertEqual(response.status, 400)
        self.assertIn("start_date must not be after end_date", self.payload(response)["error"])

    def test_invalid_date_returns_400(self) -> None:
        response = self.application.handle(
            "GET", "/api/daily-range?start_date=08-10-2026&end_date=2026-08-12"
        )
        self.assertEqual(response.status, 400)

    def test_sql_injection_is_rejected(self) -> None:
        response = self.application.handle(
            "GET",
            "/api/daily-range?start_date=2026-08-10%27%20OR%201%3D1%20--&end_date=2026-08-12",
        )
        self.assertEqual(response.status, 400)

    def test_single_day_api_is_backward_compatible(self) -> None:
        self.items.save([make_item("one", published_at=datetime(2026, 8, 10, 4, tzinfo=timezone.utc))])
        response = self.application.handle("GET", "/api/daily?date=2026-08-10")
        payload = self.payload(response)
        self.assertEqual(response.status, 200)
        self.assertEqual(payload["date"], "2026-08-10")
        self.assertEqual(payload["item_count"], 1)
        self.assertEqual(payload["companies"][0]["items"][0]["type"], "Filing")

    def test_over_100_items_are_not_truncated(self) -> None:
        self.items.save([
            make_item(f"bulk-{index}", published_at=datetime(2026, 8, 10, 4, tzinfo=timezone.utc))
            for index in range(120)
        ])
        payload = self.report("2026-08-10", "2026-08-10")
        self.assertEqual(payload["days"][0]["item_count"], 120)
        self.assertEqual(payload["item_count"], 120)

    def _add_msft_to_holdings(self) -> None:
        self.application.repository.add_companies_batch(
            "MSFT", ("holdings",), self.application.resolver
        )

    def test_dual_company_items_are_not_truncated_at_page_boundary(self) -> None:
        self._add_msft_to_holdings()
        self.items.save([
            make_item(
                f"dual-{index}",
                tickers=("AAPL", "MSFT"),
                published_at=datetime(2026, 8, 10, 4, tzinfo=timezone.utc),
            )
            for index in range(100)
        ])
        payload = self.report("2026-08-10", "2026-08-10")
        day = payload["days"][0]
        self.assertEqual(day["company_count"], 2)
        by_ticker = {c["ticker"]: c for c in day["companies"]}
        self.assertEqual(len(by_ticker["AAPL"]["items"]), 100)
        self.assertEqual(len(by_ticker["MSFT"]["items"]), 100)
        self.assertEqual(day["item_count"], 200)
        self.assertEqual(payload["item_count"], 200)
        expected_urls = {
            f"https://example.test/dual-{index}" for index in range(100)
        }
        for ticker in ("AAPL", "MSFT"):
            self.assertEqual(
                {i["url"] for i in by_ticker[ticker]["items"]},
                expected_urls,
            )

    def test_dual_company_items_over_page_boundary_are_complete(self) -> None:
        self._add_msft_to_holdings()
        self.items.save([
            make_item(
                f"dual-{index}",
                tickers=("AAPL", "MSFT"),
                published_at=datetime(2026, 8, 10, 4, tzinfo=timezone.utc),
            )
            for index in range(101)
        ])
        payload = self.report("2026-08-10", "2026-08-10")
        day = payload["days"][0]
        self.assertEqual(day["company_count"], 2)
        by_ticker = {c["ticker"]: c for c in day["companies"]}
        self.assertEqual(len(by_ticker["AAPL"]["items"]), 101)
        self.assertEqual(len(by_ticker["MSFT"]["items"]), 101)
        self.assertEqual(day["item_count"], 202)
        self.assertEqual(payload["item_count"], 202)
        expected_urls = {
            f"https://example.test/dual-{index}" for index in range(101)
        }
        for ticker in ("AAPL", "MSFT"):
            self.assertEqual(
                {i["url"] for i in by_ticker[ticker]["items"]},
                expected_urls,
            )

    def test_same_time_items_have_stable_order(self) -> None:
        self.items.save([
            make_item("z-last", published_at=datetime(2026, 8, 10, 4, tzinfo=timezone.utc)),
            make_item("a-first", published_at=datetime(2026, 8, 10, 4, tzinfo=timezone.utc)),
        ])
        first = self.report("2026-08-10", "2026-08-10")
        second = self.report("2026-08-10", "2026-08-10")
        # 相同 event time 下按 external_id 升序（再按 id）稳定排序。
        expected = [
            "https://example.test/a-first",
            "https://example.test/z-last",
        ]
        for payload in (first, second):
            urls = [i["url"] for i in payload["days"][0]["companies"][0]["items"]]
            self.assertEqual(urls, expected)

    def test_title_html_returned_verbatim_and_frontend_escapes(self) -> None:
        self.items.save([make_item(
            "xss-1", title='<script>alert("x")</script>',
            published_at=datetime(2026, 8, 10, 4, tzinfo=timezone.utc),
        )])
        payload = self.report("2026-08-10", "2026-08-10")
        item = payload["days"][0]["companies"][0]["items"][0]
        self.assertEqual(item["title"], '<script>alert("x")</script>')
        script = self.application.handle("GET", "/static/app.js")
        self.assertIn(b"esc(item.title)", script.body)
        self.assertIn(b"escAttr(url)", script.body)

    def test_existing_feed_endpoint_still_works(self) -> None:
        self.items.save([make_item("feed-1", published_at=datetime(2026, 8, 10, 4, tzinfo=timezone.utc))])
        response = self.application.handle(
            "GET", "/api/feed?start_date=2026-08-10&end_date=2026-08-10"
        )
        self.assertEqual(response.status, 200)
        self.assertEqual(self.payload(response)["pagination"]["total"], 1)


class DailyReportSourceConfigTests(_DailyRangeHarness):
    """已配置 source 的记录必须显示，未配置 source 必须被诚实隐藏。

    这是生产「No information for this date」问题的回归：数据库里已有的
    yahoo_us / seeking_alpha 记录，只有在 #29 / #31 把对应 source 正确接入
    settings / registry / allowed_sources 之后，才会重新出现在日报里。
    """

    enabled_sources = ("sec", "news", "community", "yahoo_us", "seeking_alpha")

    def test_configured_news_and_community_sources_display_on_daily(self) -> None:
        self.items.save([
            make_item(
                "yahoo-1",
                source="yahoo_us",
                source_type="news",
                published_at=datetime(2026, 8, 12, 4, tzinfo=timezone.utc),
            ),
            make_item(
                "sa-1",
                source="seeking_alpha",
                source_type="community",
                published_at=datetime(2026, 8, 12, 5, tzinfo=timezone.utc),
            ),
        ])
        response = self.application.handle("GET", "/api/daily?date=2026-08-12")
        self.assertEqual(response.status, 200)
        payload = self.payload(response)
        self.assertEqual(payload["item_count"], 2)
        self.assertEqual(payload["company_count"], 1)
        company = payload["companies"][0]
        self.assertEqual(company["ticker"], "AAPL")
        self.assertEqual(
            sorted(item["type"] for item in company["items"]),
            ["Community", "News"],
        )

    def test_unconfigured_source_is_not_displayed(self) -> None:
        self.items.save([
            make_item(
                "ghost-1",
                source="ghost_source",
                source_type="news",
                published_at=datetime(2026, 8, 12, 4, tzinfo=timezone.utc),
            ),
        ])
        response = self.application.handle("GET", "/api/daily?date=2026-08-12")
        self.assertEqual(response.status, 200)
        payload = self.payload(response)
        self.assertEqual(payload["item_count"], 0)
        self.assertEqual(payload["companies"], [])


class DailyReportDefaultDateTests(_DailyRangeHarness):
    """Daily Report 默认日期统一使用 Asia/Shanghai，而不是 Eastern。"""

    @staticmethod
    def clock() -> datetime:
        return FIXED_NOW

    def test_default_natural_day_is_shanghai(self) -> None:
        self.assertEqual(_shanghai_default_day(FIXED_NOW), date(2026, 8, 13))

    def test_daily_api_defaults_to_shanghai_day(self) -> None:
        response = self.application.handle("GET", "/api/daily")
        self.assertEqual(response.status, 200)
        self.assertEqual(self.payload(response)["date"], "2026-08-13")

    def test_daily_range_defaults_to_shanghai_day(self) -> None:
        response = self.application.handle("GET", "/api/daily-range")
        self.assertEqual(response.status, 200)
        payload = self.payload(response)
        self.assertEqual(payload["start_date"], "2026-08-13")
        self.assertEqual(payload["end_date"], "2026-08-13")
        self.assertEqual([d["date"] for d in payload["days"]], ["2026-08-13"])

    def test_bootstrap_exposes_shanghai_report_date(self) -> None:
        response = self.application.handle("GET", "/api/bootstrap")
        self.assertEqual(response.status, 200)
        payload = self.payload(response)
        self.assertEqual(payload["report_selected_date"], "2026-08-13")

    def test_app_js_uses_dedicated_report_date(self) -> None:
        script = self.application.handle("GET", "/static/app.js")
        self.assertIn(b"report_selected_date", script.body)
        self.assertNotIn(b"state.bootstrap.selected_date", script.body)

    def test_explicit_dates_ignore_default_clock(self) -> None:
        daily = self.application.handle("GET", "/api/daily?date=2026-08-02")
        self.assertEqual(self.payload(daily)["date"], "2026-08-02")
        ranged = self.application.handle(
            "GET", "/api/daily-range?start_date=2026-08-02&end_date=2026-08-03"
        )
        ranged_payload = self.payload(ranged)
        self.assertEqual(ranged_payload["start_date"], "2026-08-02")
        self.assertEqual(ranged_payload["end_date"], "2026-08-03")
        self.assertEqual(
            [d["date"] for d in ranged_payload["days"]],
            ["2026-08-03", "2026-08-02"],
        )


class DailyRangeDedupeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = TemporaryDirectory()
        self.database_path = Path(self.temporary_directory.name) / "web.sqlite3"
        self.items = SQLiteInformationRepository(self.database_path)
        self.repository = WebRepository(
            self.database_path,
            allowed_sources=("yahoo_us", "google_news_us"),
        )
        self.resolver = FakeResolver()
        self.repository.add_companies_batch(
            "AAPL", ("holdings",), self.resolver  # type: ignore[arg-type]
        )

    def tearDown(self) -> None:
        self.temporary_directory.cleanup()

    def test_soft_dedupe_keeps_all_rows_and_annotates(self) -> None:
        self.items.save([
            make_item(
                "yahoo-1", source="yahoo_us", source_type="news",
                title="Apple launches product",
                published_at=datetime(2026, 8, 10, 4, tzinfo=timezone.utc),
            ),
            make_item(
                "google-1", source="google_news_us", source_type="news",
                title="Apple launches product",
                published_at=datetime(2026, 8, 10, 4, tzinfo=timezone.utc),
            ),
        ])
        result = self.repository.query_feed_display_all(FeedFilters(
            information_type="daily",
            start_date=date(2026, 8, 10),
            end_date=date(2026, 8, 10),
            page_size=100,
        ))
        self.assertEqual(len(result.items), 2)
        labels = {
            item["external_id"]: item.get("also_seen_on_labels")
            for item in result.items
        }
        self.assertEqual(labels["yahoo-1"], ["Google News (US)"])
        self.assertEqual(labels["google-1"], ["Yahoo Finance US"])


if __name__ == "__main__":
    unittest.main()
