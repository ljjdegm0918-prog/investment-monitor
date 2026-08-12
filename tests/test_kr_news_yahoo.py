from datetime import date, datetime, timezone
from pathlib import Path
import unittest

from investment_monitor import CollectionRequest
from investment_monitor.registry import create_default_registry


FIXTURES = Path(__file__).parent / "fixtures" / "kr_news"


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


class YahooKrNewsClientTests(unittest.TestCase):
    def test_parses_rss(self) -> None:
        from investment_monitor.sources.kr_news.yahoo.client import YahooKrNewsClient, _parse_rss

        body = (FIXTURES / "yahoo_kr_005930.xml").read_bytes()
        records = _parse_rss(
            body,
            start_date=date(2026, 8, 1),
            end_date=date(2026, 8, 8),
        )
        self.assertEqual(len(records), 2)
        self.assertEqual(records[0]["title"], "삼성전자 분기 실적 호조")

        opener = FakeBilingualOpener(
            (FIXTURES / "yahoo_kr_005930.xml").read_bytes(),
            (FIXTURES / "yahoo_kr_005930_en.xml").read_bytes(),
            "ko-KR",
        )
        client = YahooKrNewsClient(
            opener=opener,
            requests_per_second=1000,
        )
        fetched = client.fetch_news(
            "005930.KS",
            date(2026, 8, 1),
            date(2026, 8, 8),
        )
        self.assertEqual(len(fetched), 2)
        self.assertIn("s=005930.KS", opener.requested[0])
        self.assertIn("region=KR", opener.requested[0])
        self.assertIn("lang=ko-KR", opener.requested[0])

    def test_kr_day_boundary_uses_seoul_timezone(self) -> None:
        from investment_monitor.sources.kr_news.yahoo.client import YahooKrNewsClient

        # 23:30 UTC 是 KST 次日 08:30，必须归入次日（KST），而不是 UTC 当日。
        body = (
            b'<?xml version="1.0" encoding="UTF-8"?>'
            b'<rss version="2.0"><channel><item>'
            b'<title>Boundary headline</title>'
            b'<link>https://finance.yahoo.com/news/230000.html</link>'
            b'<pubDate>Mon, 10 Aug 2026 23:30:00 +0000</pubDate>'
            b'<description>Boundary fixture.</description>'
            b'</item></channel></rss>'
        )
        client = YahooKrNewsClient(
            opener=FakeOpener(body),
            requests_per_second=1000,
        )
        next_day = client.fetch_news(
            "005930.KS", date(2026, 8, 11), date(2026, 8, 11)
        )
        self.assertEqual(len(next_day), 1)
        same_utc_day = client.fetch_news(
            "005930.KS", date(2026, 8, 10), date(2026, 8, 10)
        )
        self.assertEqual(len(same_utc_day), 0)


class YahooKrNewsConnectorTests(unittest.TestCase):
    def request(self, tickers, markets):
        return CollectionRequest(
            tickers=tickers,
            start_date=date(2026, 8, 1),
            end_date=date(2026, 8, 8),
            markets=markets,
        )

    def make_connector(self):
        from investment_monitor.sources.kr_news.yahoo.client import YahooKrNewsClient
        from investment_monitor.sources.kr_news.yahoo.connector import YahooKrNewsConnector

        opener = FakeBilingualOpener(
            (FIXTURES / "yahoo_kr_005930.xml").read_bytes(),
            (FIXTURES / "yahoo_kr_005930_en.xml").read_bytes(),
            "ko-KR",
        )
        connector = YahooKrNewsConnector(
            client=YahooKrNewsClient(
                opener=opener,
                requests_per_second=1000,
            ),
        )
        return connector, opener

    def test_maps_news_with_canonical_ticker(self) -> None:
        connector, opener = self.make_connector()
        items = connector.collect(
            self.request(("005930",), {"005930": "kr"})
        )
        self.assertEqual(len(items), 4)
        self.assertEqual(items[0].source, "yahoo_kr")
        self.assertEqual(items[0].tickers, ("005930",))

    def test_registry_registers_without_secret_field(self) -> None:
        registry = create_default_registry()
        self.assertIsNotNone(registry.factory_for("yahoo_kr"))


if __name__ == "__main__":
    unittest.main()
