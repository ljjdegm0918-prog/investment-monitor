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


class YahooUsNewsClientTests(unittest.TestCase):
    def test_parses_rss(self) -> None:
        from investment_monitor.sources.us_news.yahoo.client import YahooUsNewsClient, _parse_rss

        body = (FIXTURES / "yahoo_us_aapl.xml").read_bytes()
        records = _parse_rss(
            body,
            start_date=date(2026, 8, 1),
            end_date=date(2026, 8, 8),
        )
        self.assertEqual(len(records), 2)
        self.assertEqual(records[0]["title"], "Apple shares rise on earnings")

        opener = FakeOpener((FIXTURES / "yahoo_us_aapl.xml").read_bytes())
        client = YahooUsNewsClient(
            opener=opener,
            requests_per_second=1000,
        )
        fetched = client.fetch_news(
            "AAPL",
            date(2026, 8, 1),
            date(2026, 8, 8),
        )
        self.assertEqual(len(fetched), 2)
        self.assertIn("s=AAPL", opener.requested[0])
        self.assertIn("region=US", opener.requested[0])
        self.assertIn("lang=en-US", opener.requested[0])


class YahooUsNewsConnectorTests(unittest.TestCase):
    def request(self, tickers, markets):
        return CollectionRequest(
            tickers=tickers,
            start_date=date(2026, 8, 1),
            end_date=date(2026, 8, 8),
            markets=markets,
        )

    def make_connector(self):
        from investment_monitor.sources.us_news.yahoo.client import YahooUsNewsClient
        from investment_monitor.sources.us_news.yahoo.connector import YahooUsNewsConnector

        opener = FakeOpener((FIXTURES / "yahoo_us_aapl.xml").read_bytes())
        connector = YahooUsNewsConnector(
            client=YahooUsNewsClient(
                opener=opener,
                requests_per_second=1000,
            ),
        )
        return connector, opener

    def test_maps_news_with_canonical_ticker(self) -> None:
        connector, opener = self.make_connector()
        items = connector.collect(
            self.request(("AAPL",), {"AAPL": "us"})
        )
        self.assertEqual(len(items), 2)
        self.assertEqual(items[0].source, "yahoo_us")
        self.assertEqual(items[0].tickers, ("AAPL",))

    def test_registry_registers_without_secret_field(self) -> None:
        registry = create_default_registry()
        self.assertIsNotNone(registry.factory_for("yahoo_us"))


if __name__ == "__main__":
    unittest.main()
