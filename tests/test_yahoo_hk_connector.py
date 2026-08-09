from datetime import date, datetime, timezone
from pathlib import Path
import unittest

from investment_monitor import (
    CollectionRequest,
    YahooHkNewsConnector,
    YahooHkNewsDataError,
    YahooHkNewsRequestError,
)
from investment_monitor.registry import create_default_registry


FIXTURES = Path(__file__).parent / "fixtures" / "hk_news"


class FakeResponse:
    def __init__(self, body: bytes) -> None:
        self._body = body

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return None

    def read(self) -> bytes:
        return self._body


class FakeOpener:
    def __init__(self, zh: bytes, en: bytes) -> None:
        self.zh = zh
        self.en = en
        self.requested: list = []

    def __call__(self, request, timeout=None):
        url = request.full_url
        self.requested.append(url)
        body = self.zh if "lang=zh-Hant-HK" in url else self.en
        return FakeResponse(body)


class YahooHkClientTests(unittest.TestCase):
    def test_parses_rss_and_filters_dates(self) -> None:
        from investment_monitor.sources.hk_news.yahoo.client import (
            YahooHkNewsClient,
            _parse_rss,
        )

        body = (FIXTURES / "yahoo_0700_zh.xml").read_bytes()
        records = _parse_rss(
            body,
            start_date=date(2026, 8, 1),
            end_date=date(2026, 8, 5),
        )

        self.assertEqual(len(records), 2)
        first = records[0]
        self.assertEqual(first["external_id"], "110000001")
        self.assertEqual(first["title"], "騰訊控股季度業績公布")
        self.assertEqual(
            first["url"],
            "https://hk.finance.yahoo.com/news/tencent-quarterly-110000001.html",
        )
        self.assertEqual(
            first["published"],
            datetime(2026, 8, 5, 9, 30, tzinfo=timezone.utc),
        )
        self.assertEqual(first["summary"], "騰訊公布季度業績。")

        opener = FakeOpener(
            (FIXTURES / "yahoo_0700_zh.xml").read_bytes(),
            b"",
        )
        client = YahooHkNewsClient(
            opener=opener,
            requests_per_second=1000,
        )
        fetched = client.fetch_news(
            "0700.HK",
            date(2026, 8, 1),
            date(2026, 8, 5),
        )
        self.assertEqual(len(fetched), 2)
        self.assertIn("s=0700.HK", opener.requested[0])
        self.assertIn("region=HK", opener.requested[0])
        self.assertIn("lang=zh-Hant-HK", opener.requested[0])

    def test_empty_channel_returns_empty_list(self) -> None:
        from investment_monitor.sources.hk_news.yahoo.client import _parse_rss

        body = b'<?xml version="1.0"?><rss version="2.0"><channel><title>x</title></channel></rss>'
        records = _parse_rss(
            body,
            start_date=date(2026, 8, 1),
            end_date=date(2026, 8, 5),
        )

        self.assertEqual(records, [])

    def test_malformed_feed_raises_data_error(self) -> None:
        from investment_monitor.sources.hk_news.yahoo.client import _parse_rss

        with self.assertRaises(YahooHkNewsDataError):
            _parse_rss(
                b"<html><body>blocked</body></html>",
                start_date=date(2026, 8, 1),
                end_date=date(2026, 8, 5),
            )


class YahooHkSymbolTests(unittest.TestCase):
    def test_yahoo_symbol_rules(self) -> None:
        from investment_monitor.sources.hk_news.yahoo.connector import (
            _yahoo_symbol,
        )

        self.assertEqual(_yahoo_symbol("00700"), "0700.HK")
        self.assertEqual(_yahoo_symbol("0700"), "0700.HK")
        self.assertEqual(_yahoo_symbol("09988"), "9988.HK")
        self.assertEqual(_yahoo_symbol("00001"), "0001.HK")
        self.assertEqual(_yahoo_symbol("0700.HK"), "0700.HK")
        self.assertEqual(_yahoo_symbol("VOD"), "VOD.HK")


class YahooHkConnectorTests(unittest.TestCase):
    def request(self, tickers, markets):
        return CollectionRequest(
            tickers=tickers,
            start_date=date(2026, 8, 1),
            end_date=date(2026, 8, 6),
            markets=markets,
        )

    def make_connector(self):
        from investment_monitor.sources.hk_news.yahoo.client import (
            YahooHkNewsClient,
        )

        opener = FakeOpener(
            (FIXTURES / "yahoo_0700_zh.xml").read_bytes(),
            (FIXTURES / "yahoo_0700_en.xml").read_bytes(),
        )
        return YahooHkNewsConnector(
            client=YahooHkNewsClient(
                opener=opener,
                requests_per_second=1000,
            )
        ), opener

    def test_non_hk_markets_are_skipped_with_zero_http(self) -> None:
        from investment_monitor.sources.hk_news.yahoo.client import (
            YahooHkNewsClient,
        )

        opener = FakeOpener(b"", b"")
        connector = YahooHkNewsConnector(
            client=YahooHkNewsClient(
                opener=opener,
                requests_per_second=1000,
            )
        )

        items = connector.collect(
            self.request(("AAPL", "VOD"), {"AAPL": "us", "VOD": "uk"})
        )

        self.assertEqual(items, [])
        self.assertEqual(connector.last_errors, ())
        self.assertEqual(opener.requested, [])

    def test_hk_maps_news_with_canonical_ticker(self) -> None:
        connector, opener = self.make_connector()

        items = connector.collect(
            self.request(("00700",), {"00700": "hk"})
        )

        by_id = {item.external_id: item for item in items}
        self.assertIn("110000001", by_id)
        first = by_id["110000001"]
        self.assertEqual(first.source, "yahoo_hk")
        self.assertEqual(first.source_type, "news")
        self.assertEqual(first.tickers, ("00700",))
        self.assertEqual(first.market, "hk")
        self.assertEqual(first.document_type, "news")
        self.assertEqual(first.raw_metadata["provider"], "yahoo_finance_rss")
        self.assertIn("s=0700.HK", opener.requested[0])
        self.assertNotIn("s=00700.HK", opener.requested[0])

    def test_bilingual_records_merge_by_article_id(self) -> None:
        connector, _ = self.make_connector()

        items = connector.collect(
            self.request(("00700",), {"00700": "hk"})
        )

        by_id = {item.external_id: item for item in items}
        merged = by_id["110000001"]
        self.assertEqual(merged.title, "Tencent announces quarterly results")
        self.assertEqual(merged.raw_metadata["title_zh"], "騰訊控股季度業績公布")
        self.assertEqual(merged.raw_metadata["title_en"], "Tencent announces quarterly results")
        self.assertEqual(merged.raw_metadata["langs"], "en+zh")
        zh_only = by_id["110000002"]
        self.assertEqual(zh_only.title, "港股通淨流入")
        self.assertEqual(zh_only.raw_metadata["langs"], "zh")
        self.assertNotIn("title_en", zh_only.raw_metadata)
        en_only = by_id["110000004"]
        self.assertEqual(en_only.title, "New listing announcement")
        self.assertEqual(en_only.raw_metadata["langs"], "en")

    def test_identical_bilingual_titles_are_not_fake_bilingual(self) -> None:
        from investment_monitor.sources.hk_news.yahoo.connector import _map_news

        zh = [{
            "external_id": "110000009",
            "title": "重複標題",
            "url": "https://hk.finance.yahoo.com/news/dup-110000009.html",
            "published": datetime(2026, 8, 5, 9, 0, tzinfo=timezone.utc),
            "summary": None,
        }]
        en = [{
            "external_id": "110000009",
            "title": "重複標題",
            "url": "https://hk.finance.yahoo.com/news/dup-110000009.html",
            "published": datetime(2026, 8, 5, 9, 0, tzinfo=timezone.utc),
            "summary": None,
        }]

        items = _map_news(
            zh,
            en,
            code="00700",
            collected_at=datetime(2026, 8, 6, tzinfo=timezone.utc),
        )

        self.assertEqual(len(items), 1)
        self.assertEqual(items[0].raw_metadata["langs"], "zh")
        self.assertNotIn("title_en", items[0].raw_metadata)
        self.assertEqual(items[0].raw_metadata["title_zh"], "重複標題")

    def test_single_ticker_failure_raises_and_records_error(self) -> None:
        from investment_monitor.sources.hk_news.yahoo.client import (
            YahooHkNewsClient,
        )

        def failing_opener(request, timeout=None):
            raise YahooHkNewsRequestError("yahoo blocked")

        connector = YahooHkNewsConnector(
            client=YahooHkNewsClient(
                opener=failing_opener,
                requests_per_second=1000,
            )
        )

        with self.assertRaises(YahooHkNewsRequestError):
            connector.collect(self.request(("00700",), {"00700": "hk"}))

        self.assertEqual(len(connector.last_errors), 1)
        self.assertEqual(connector.last_errors[0][0], "00700")

    def test_registry_registers_yahoo_hk_without_secret_field(self) -> None:
        registry = create_default_registry()

        self.assertIsNotNone(registry.factory_for("yahoo_hk"))
        self.assertEqual(registry.secret_fields_for("yahoo_hk"), ())


if __name__ == "__main__":
    unittest.main()
