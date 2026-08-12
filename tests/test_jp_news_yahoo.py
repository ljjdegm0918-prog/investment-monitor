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


class YahooJpNewsClientTests(unittest.TestCase):
    def test_parses_rss(self) -> None:
        from investment_monitor.sources.jp_news.yahoo.client import YahooJpNewsClient, _parse_rss

        body = (FIXTURES / "yahoo_jp_7203.xml").read_bytes()
        records = _parse_rss(
            body,
            start_date=date(2026, 8, 1),
            end_date=date(2026, 8, 8),
        )
        self.assertEqual(len(records), 2)
        self.assertEqual(records[0]["title"], "トヨタ決算が市場予想上回る")

        opener = FakeOpener((FIXTURES / "yahoo_jp_7203.xml").read_bytes())
        client = YahooJpNewsClient(
            opener=opener,
            requests_per_second=1000,
        )
        fetched = client.fetch_news(
            "7203.T",
            date(2026, 8, 1),
            date(2026, 8, 8),
        )
        self.assertEqual(len(fetched), 2)
        self.assertIn("s=7203.T", opener.requested[0])
        self.assertIn("region=JP", opener.requested[0])
        self.assertIn("lang=ja-JP", opener.requested[0])


class YahooJpNewsConnectorTests(unittest.TestCase):
    def request(self, tickers, markets):
        return CollectionRequest(
            tickers=tickers,
            start_date=date(2026, 8, 1),
            end_date=date(2026, 8, 8),
            markets=markets,
        )

    def make_connector(self):
        from investment_monitor.sources.jp_news.yahoo.client import YahooJpNewsClient
        from investment_monitor.sources.jp_news.yahoo.connector import YahooJpNewsConnector

        opener = FakeOpener((FIXTURES / "yahoo_jp_7203.xml").read_bytes())
        connector = YahooJpNewsConnector(
            client=YahooJpNewsClient(
                opener=opener,
                requests_per_second=1000,
            ),
        )
        return connector, opener

    def test_maps_news_with_canonical_ticker(self) -> None:
        connector, opener = self.make_connector()
        items = connector.collect(
            self.request(("7203.T",), {"7203.T": "jp"})
        )
        self.assertEqual(len(items), 2)
        self.assertEqual(items[0].source, "yahoo_jp")
        self.assertEqual(items[0].tickers, ("7203",))

    def test_registry_registers_without_secret_field(self) -> None:
        registry = create_default_registry()
        self.assertIsNotNone(registry.factory_for("yahoo_jp"))


if __name__ == "__main__":
    unittest.main()
