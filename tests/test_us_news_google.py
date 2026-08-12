from datetime import date, datetime, timezone
from pathlib import Path
import unittest

from investment_monitor import CollectionRequest
from investment_monitor.registry import create_default_registry


FIXTURES = Path(__file__).parent / "fixtures" / "us_news"


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


class GoogleUsNewsClientTests(unittest.TestCase):
    def test_parses_rss_and_builds_query(self) -> None:
        from investment_monitor.sources.us_news.google.client import GoogleUsNewsClient, _parse_rss

        body = (FIXTURES / "google_us_aapl.xml").read_bytes()
        records = _parse_rss(
            body,
            start_date=date(2026, 8, 1),
            end_date=date(2026, 8, 8),
        )
        self.assertEqual(len(records), 2)
        self.assertEqual(records[0]["title"], "Apple beats earnings estimates")

        opener = FakeOpener(body)
        client = GoogleUsNewsClient(
            opener=opener,
            requests_per_second=1000,
        )
        fetched = client.fetch_news(
            "AAPL",
            date(2026, 8, 1),
            date(2026, 8, 8),
        )
        self.assertEqual(len(fetched), 2)
        self.assertIn("q=AAPL", opener.requested[0])
        self.assertIn("hl=en-US", opener.requested[0])
        self.assertIn("gl=US", opener.requested[0])
        self.assertIn("ceid=US:en", opener.requested[0])

    def test_malformed_feed_raises_data_error(self) -> None:
        from investment_monitor.sources.us_news.google.client import _parse_rss, GoogleUsNewsDataError

        with self.assertRaises(GoogleUsNewsDataError):
            _parse_rss(
                b"<html><body>blocked</body></html>",
                start_date=date(2026, 8, 1),
                end_date=date(2026, 8, 8),
            )


class GoogleUsNewsConnectorTests(unittest.TestCase):
    def request(self, tickers, markets):
        return CollectionRequest(
            tickers=tickers,
            start_date=date(2026, 8, 1),
            end_date=date(2026, 8, 8),
            markets=markets,
        )

    def make_connector(self, symbol_for=None):
        from investment_monitor.sources.us_news.google.client import GoogleUsNewsClient
        from investment_monitor.sources.us_news.google.connector import GoogleUsNewsConnector

        opener = FakeOpener((FIXTURES / "google_us_aapl.xml").read_bytes())
        connector = GoogleUsNewsConnector(
            client=GoogleUsNewsClient(
                opener=opener,
                requests_per_second=1000,
            ),
            symbol_for=symbol_for,
        )
        return connector, opener

    def test_non_market_skipped(self) -> None:
        connector, opener = self.make_connector()
        items = connector.collect(
            self.request(("VOD", "PKO"), {"VOD": "uk", "PKO": "pl"})
        )
        self.assertEqual(items, [])
        self.assertEqual(opener.requested, [])

    def test_maps_news_with_canonical_ticker(self) -> None:
        connector, opener = self.make_connector()
        items = connector.collect(
            self.request(("AAPL",), {"AAPL": "us"})
        )
        self.assertEqual(len(items), 2)
        first = items[0]
        self.assertEqual(first.source, "google_news_us")
        self.assertEqual(first.tickers, ("AAPL",))
        self.assertEqual(first.market, "us")

    def test_registry_registers_without_secret_field(self) -> None:
        registry = create_default_registry()
        self.assertIsNotNone(registry.factory_for("google_news_us"))
        self.assertEqual(registry.secret_fields_for("google_news_us"), ())


if __name__ == "__main__":
    unittest.main()
