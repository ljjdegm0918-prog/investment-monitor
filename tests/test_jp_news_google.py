from datetime import date, datetime, timezone
from pathlib import Path
import unittest

from investment_monitor import CollectionRequest
from investment_monitor.registry import create_default_registry


FIXTURES = Path(__file__).parent / "fixtures" / "jp_news"


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
        url = request.full_url
        self.requested.append(url)
        return FakeResponse(self.body)


class FakeBilingualOpener:
    def __init__(self, primary: bytes, en: bytes, primary_lang: str) -> None:
        self.primary = primary
        self.en = en
        self.primary_lang = primary_lang
        self.requested: list = []

    def __call__(self, request, timeout=None):
        url = request.full_url
        self.requested.append(url)
        body = self.primary if f"lang={self.primary_lang}" in url else self.en
        return FakeResponse(body)


class GoogleJpNewsClientTests(unittest.TestCase):
    def test_parses_rss_and_builds_query(self) -> None:
        from investment_monitor.sources.jp_news.google.client import GoogleJpNewsClient, _parse_rss

        body = (FIXTURES / "google_jp_7203.xml").read_bytes()
        records = _parse_rss(
            body,
            start_date=date(2026, 8, 1),
            end_date=date(2026, 8, 8),
        )
        self.assertEqual(len(records), 2)
        self.assertEqual(records[0]["title"], "トヨタ自動車が決算発表")

        opener = FakeOpener(body)
        client = GoogleJpNewsClient(
            opener=opener,
            requests_per_second=1000,
        )
        fetched = client.fetch_news(
            "7203.T",
            date(2026, 8, 1),
            date(2026, 8, 8),
        )
        self.assertEqual(len(fetched), 2)
        self.assertIn("q=7203.T", opener.requested[0])
        self.assertIn("hl=ja", opener.requested[0])
        self.assertIn("gl=JP", opener.requested[0])
        self.assertIn("ceid=JP:ja", opener.requested[0])

    def test_malformed_feed_raises_data_error(self) -> None:
        from investment_monitor.sources.jp_news.google.client import _parse_rss, GoogleJpNewsDataError

        with self.assertRaises(GoogleJpNewsDataError):
            _parse_rss(
                b"<html><body>blocked</body></html>",
                start_date=date(2026, 8, 1),
                end_date=date(2026, 8, 8),
            )


class GoogleJpNewsConnectorTests(unittest.TestCase):
    def request(self, tickers, markets):
        return CollectionRequest(
            tickers=tickers,
            start_date=date(2026, 8, 1),
            end_date=date(2026, 8, 8),
            markets=markets,
        )

    def make_connector(self, symbol_for=None):
        from investment_monitor.sources.jp_news.google.client import GoogleJpNewsClient
        from investment_monitor.sources.jp_news.google.connector import GoogleJpNewsConnector

        opener = FakeOpener((FIXTURES / "google_jp_7203.xml").read_bytes())
        connector = GoogleJpNewsConnector(
            client=GoogleJpNewsClient(
                opener=opener,
                requests_per_second=1000,
            ),
            symbol_for=symbol_for,
        )
        return connector, opener

    def test_non_market_skipped(self) -> None:
        connector, opener = self.make_connector()
        items = connector.collect(
            self.request(("AAPL", "VOD"), {"AAPL": "us", "VOD": "uk"})
        )
        self.assertEqual(items, [])
        self.assertEqual(opener.requested, [])

    def test_maps_news_with_canonical_ticker(self) -> None:
        connector, opener = self.make_connector()
        items = connector.collect(
            self.request(("7203.T",), {"7203.T": "jp"})
        )
        self.assertEqual(len(items), 2)
        first = items[0]
        self.assertEqual(first.source, "google_news_jp")
        self.assertEqual(first.tickers, ("7203",))
        self.assertEqual(first.market, "jp")

    def test_registry_registers_without_secret_field(self) -> None:
        registry = create_default_registry()
        self.assertIsNotNone(registry.factory_for("google_news_jp"))
        self.assertEqual(registry.secret_fields_for("google_news_jp"), ())


if __name__ == "__main__":
    unittest.main()
