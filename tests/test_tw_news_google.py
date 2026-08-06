from datetime import date, datetime, timezone
from pathlib import Path
import unittest

from investment_monitor import (
    CollectionRequest,
    GoogleTwNewsConnector,
    GoogleTwNewsRequestError,
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
    def __init__(self, body: bytes) -> None:
        self.body = body
        self.requested: list = []

    def __call__(self, request, timeout=None):
        self.requested.append(request.full_url)
        return FakeResponse(self.body)


class GoogleTwNewsTests(unittest.TestCase):
    def request(self, tickers, markets):
        return CollectionRequest(
            tickers=tickers,
            start_date=date(2026, 8, 1),
            end_date=date(2026, 8, 5),
            markets=markets,
        )

    def make_connector(self, body=None):
        from investment_monitor.sources.tw_news.google.client import (
            GoogleTwNewsClient,
        )

        opener = FakeOpener(
            body or (FIXTURES / "google_tw_2330.xml").read_bytes()
        )
        return (
            GoogleTwNewsConnector(
                client=GoogleTwNewsClient(
                    opener=opener,
                    requests_per_second=1000,
                )
            ),
            opener,
        )

    def test_client_fetches_zh_tw_google_news(self) -> None:
        from investment_monitor.sources.tw_news.google.client import (
            GoogleTwNewsClient,
            _parse_rss,
        )

        body = (FIXTURES / "google_tw_2330.xml").read_bytes()
        records = _parse_rss(
            body,
            start_date=date(2026, 8, 1),
            end_date=date(2026, 8, 5),
        )
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["title"], "台積電法說會重點整理")

        opener = FakeOpener(body)
        client = GoogleTwNewsClient(
            opener=opener,
            requests_per_second=1000,
        )
        fetched = client.fetch_news(
            "2330.TW",
            date(2026, 8, 1),
            date(2026, 8, 5),
        )
        self.assertEqual(len(fetched), 1)
        self.assertIn("q=2330.TW", opener.requested[0])
        self.assertIn("hl=zh-TW", opener.requested[0])

    def test_non_tw_markets_are_skipped_with_zero_http(self) -> None:
        connector, opener = self.make_connector()

        items = connector.collect(
            self.request(("AAPL",), {"AAPL": "us"})
        )

        self.assertEqual(items, [])
        self.assertEqual(connector.last_errors, ())
        self.assertEqual(opener.requested, [])

    def test_tw_maps_google_news_items(self) -> None:
        connector, opener = self.make_connector()

        items = connector.collect(
            self.request(("2330",), {"2330": "tw"})
        )

        self.assertEqual(len(items), 1)
        first = items[0]
        self.assertEqual(first.source, "google_news_tw")
        self.assertEqual(first.source_type, "news")
        self.assertEqual(first.tickers, ("2330",))
        self.assertEqual(first.market, "tw")
        self.assertEqual(first.title, "台積電法說會重點整理")
        self.assertTrue(first.external_id)
        self.assertIn("q=2330.TW", opener.requested[0])

    def test_single_ticker_failure_raises(self) -> None:
        from investment_monitor.sources.tw_news.google.client import (
            GoogleTwNewsClient,
        )

        def failing_opener(request, timeout=None):
            raise GoogleTwNewsRequestError("google blocked")

        connector = GoogleTwNewsConnector(
            client=GoogleTwNewsClient(
                opener=failing_opener,
                requests_per_second=1000,
            )
        )

        with self.assertRaises(GoogleTwNewsRequestError):
            connector.collect(self.request(("2330",), {"2330": "tw"}))

        self.assertEqual(len(connector.last_errors), 1)

    def test_registry_registers_without_secret_field(self) -> None:
        registry = create_default_registry()

        self.assertIsNotNone(registry.factory_for("google_news_tw"))
        self.assertEqual(registry.secret_fields_for("google_news_tw"), ())


if __name__ == "__main__":
    unittest.main()
