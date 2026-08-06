from datetime import date, datetime, timezone
from pathlib import Path
import unittest

from investment_monitor import (
    CollectionRequest,
    YahooTwNewsConnector,
    YahooTwNewsDataError,
    YahooTwNewsRequestError,
)
from investment_monitor.registry import create_default_registry


FIXTURES = Path(__file__).parent / "fixtures" / "tw_news"


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
        body = self.zh if "lang=zh-TW" in url else self.en
        return FakeResponse(body)


def make_connector(zh=None, en=None, symbol_for=None):
    from investment_monitor.sources.tw_news.yahoo.client import (
        YahooTwNewsClient,
    )

    opener = FakeOpener(
        zh or (FIXTURES / "yahoo_tw_2330.xml").read_bytes(),
        en or (FIXTURES / "yahoo_tw_2330_en.xml").read_bytes(),
    )
    return (
        YahooTwNewsConnector(
            client=YahooTwNewsClient(
                opener=opener,
                requests_per_second=1000,
            ),
            symbol_for=symbol_for,
        ),
        opener,
    )


class YahooTwNewsClientTests(unittest.TestCase):
    def test_parses_rss_and_filters_dates(self) -> None:
        from investment_monitor.sources.tw_news.yahoo.client import (
            YahooTwNewsClient,
            _parse_rss,
        )

        body = (FIXTURES / "yahoo_tw_2330.xml").read_bytes()
        records = _parse_rss(
            body,
            start_date=date(2026, 8, 1),
            end_date=date(2026, 8, 5),
        )

        self.assertEqual(len(records), 2)
        self.assertEqual(records[0]["external_id"], "110000001")
        self.assertEqual(records[0]["title"], "台積電公布一一五年七月營收")
        self.assertEqual(
            records[0]["published"],
            datetime(2026, 8, 5, 9, 30, tzinfo=timezone.utc),
        )

        opener = FakeOpener(
            (FIXTURES / "yahoo_tw_2330.xml").read_bytes(),
            b"",
        )
        client = YahooTwNewsClient(
            opener=opener,
            requests_per_second=1000,
        )
        fetched = client.fetch_news(
            "2330.TW",
            date(2026, 8, 1),
            date(2026, 8, 5),
        )
        self.assertEqual(len(fetched), 2)
        self.assertIn("s=2330.TW", opener.requested[0])
        self.assertIn("region=TW", opener.requested[0])
        self.assertIn("lang=zh-TW", opener.requested[0])

    def test_malformed_feed_raises_data_error(self) -> None:
        from investment_monitor.sources.tw_news.yahoo.client import _parse_rss

        with self.assertRaises(YahooTwNewsDataError):
            _parse_rss(
                b"<html>blocked</html>",
                start_date=date(2026, 8, 1),
                end_date=date(2026, 8, 5),
            )


class YahooTwNewsConnectorTests(unittest.TestCase):
    def request(self, tickers, markets):
        return CollectionRequest(
            tickers=tickers,
            start_date=date(2026, 8, 1),
            end_date=date(2026, 8, 6),
            markets=markets,
        )

    def test_non_tw_markets_are_skipped_with_zero_http(self) -> None:
        from investment_monitor.sources.tw_news.yahoo.client import (
            YahooTwNewsClient,
        )

        opener = FakeOpener(b"", b"")
        connector = YahooTwNewsConnector(
            client=YahooTwNewsClient(
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

    def test_tw_maps_news_with_canonical_ticker(self) -> None:
        connector, opener = make_connector()

        items = connector.collect(
            self.request(("2330",), {"2330": "tw"})
        )

        by_id = {item.external_id: item for item in items}
        self.assertIn("110000001", by_id)
        merged = by_id["110000001"]
        self.assertEqual(merged.source, "yahoo_tw")
        self.assertEqual(merged.source_type, "news")
        self.assertEqual(merged.tickers, ("2330",))
        self.assertEqual(merged.market, "tw")
        self.assertEqual(merged.title, "TSMC posts record July revenue")
        self.assertEqual(merged.raw_metadata["title_zh"], "台積電公布一一五年七月營收")
        self.assertEqual(merged.raw_metadata["langs"], "en+zh")
        self.assertEqual(by_id["110000002"].raw_metadata["langs"], "zh")
        self.assertEqual(by_id["110000004"].raw_metadata["langs"], "en")
        self.assertIn("s=2330.TW", opener.requested[0])

    def test_tpex_board_uses_two_suffix(self) -> None:
        connector, opener = make_connector(
            symbol_for=lambda code: f"{code}.TWO"
        )

        connector.collect(self.request(("1240",), {"1240": "tw"}))

        self.assertIn("s=1240.TWO", opener.requested[0])

    def test_single_ticker_failure_raises(self) -> None:
        from investment_monitor.sources.tw_news.yahoo.client import (
            YahooTwNewsClient,
        )

        def failing_opener(request, timeout=None):
            raise YahooTwNewsRequestError("yahoo blocked")

        connector = YahooTwNewsConnector(
            client=YahooTwNewsClient(
                opener=failing_opener,
                requests_per_second=1000,
            )
        )

        with self.assertRaises(YahooTwNewsRequestError):
            connector.collect(self.request(("2330",), {"2330": "tw"}))

        self.assertEqual(len(connector.last_errors), 1)

    def test_registry_registers_without_secret_field(self) -> None:
        registry = create_default_registry()

        self.assertIsNotNone(registry.factory_for("yahoo_tw"))
        self.assertEqual(registry.secret_fields_for("yahoo_tw"), ())


if __name__ == "__main__":
    unittest.main()
