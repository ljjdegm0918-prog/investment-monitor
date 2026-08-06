from datetime import date, datetime, timezone
from pathlib import Path
import unittest

from investment_monitor import (
    CollectionRequest,
    YahooNewsConnector,
    YahooNewsDataError,
    YahooNewsRequestError,
)


FIXTURES = Path(__file__).parent / "fixtures" / "uk_news"


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


class YahooNewsClientTests(unittest.TestCase):
    def test_parses_rss_and_filters_dates(self) -> None:
        from investment_monitor.sources.uk_news.yahoo.client import (
            YahooNewsClient,
            _parse_rss,
        )

        body = (FIXTURES / "yahoo_vod.xml").read_bytes()
        records = _parse_rss(
            body,
            start_date=date(2026, 8, 1),
            end_date=date(2026, 8, 5),
        )

        self.assertEqual(len(records), 1)
        first = records[0]
        self.assertEqual(first["external_id"], "110000619")
        self.assertEqual(first["title"], "Vodafone completes VodafoneZiggo exit")
        self.assertEqual(first["url"], "https://finance.yahoo.com/markets/stocks/articles/vodafone-ziggo-exit-110000619.html")
        self.assertEqual(
            first["published"],
            datetime(2026, 8, 3, 11, 0, tzinfo=timezone.utc),
        )
        self.assertEqual(
            first["summary"],
            "Vodafone has completed the sale of VodafoneZiggo.",
        )

        opener = FakeOpener(body)
        client = YahooNewsClient(opener=opener, requests_per_second=1000)
        fetched = client.fetch_news(
            "VOD.L",
            date(2026, 8, 1),
            date(2026, 8, 5),
        )
        self.assertEqual(len(fetched), 1)
        self.assertIn("s=VOD.L", opener.requested[0])

    def test_empty_channel_returns_empty_list(self) -> None:
        from investment_monitor.sources.uk_news.yahoo.client import _parse_rss

        body = b'<?xml version="1.0"?><rss version="2.0"><channel><title>x</title></channel></rss>'
        records = _parse_rss(
            body,
            start_date=date(2026, 8, 1),
            end_date=date(2026, 8, 5),
        )

        self.assertEqual(records, [])

    def test_malformed_feed_raises_data_error(self) -> None:
        from investment_monitor.sources.uk_news.yahoo.client import _parse_rss

        with self.assertRaises(YahooNewsDataError):
            _parse_rss(
                b"<html><body>blocked</body></html>",
                start_date=date(2026, 8, 1),
                end_date=date(2026, 8, 5),
            )


class YahooNewsConnectorTests(unittest.TestCase):
    def request(self, tickers, markets):
        return CollectionRequest(
            tickers=tickers,
            start_date=date(2026, 8, 1),
            end_date=date(2026, 8, 5),
            markets=markets,
        )

    def test_non_uk_markets_are_skipped_with_zero_http(self) -> None:
        from investment_monitor.sources.uk_news.yahoo.client import (
            YahooNewsClient,
        )

        opener = FakeOpener((FIXTURES / "yahoo_vod.xml").read_bytes())
        connector = YahooNewsConnector(
            client=YahooNewsClient(opener=opener, requests_per_second=1000)
        )
        items = connector.collect(
            self.request(("AAPL", "VOD"), {"AAPL": "us", "VOD": "kr"})
        )

        self.assertEqual(items, [])
        self.assertEqual(connector.last_errors, ())
        self.assertEqual(opener.requested, [])

    def test_uk_maps_news_and_adds_dot_l_at_request_time(self) -> None:
        from investment_monitor.sources.uk_news.yahoo.client import (
            YahooNewsClient,
        )

        opener = FakeOpener((FIXTURES / "yahoo_vod.xml").read_bytes())
        connector = YahooNewsConnector(
            client=YahooNewsClient(opener=opener, requests_per_second=1000)
        )

        items = connector.collect(
            self.request(("VOD",), {"VOD": "uk"})
        )

        self.assertEqual(len(items), 1)
        first = items[0]
        self.assertEqual(first.source, "yahoo_uk")
        self.assertEqual(first.source_type, "news")
        self.assertEqual(first.external_id, "110000619")
        self.assertEqual(first.tickers, ("VOD",))
        self.assertEqual(first.market, "uk")
        self.assertEqual(first.title, "Vodafone completes VodafoneZiggo exit")
        self.assertIn("s=VOD.L", opener.requested[0])
        self.assertEqual(first.raw_metadata["provider"], "yahoo_finance_rss")

    def test_dotted_ticker_keeps_dot_and_maps_to_yahoo_symbol(self) -> None:
        from investment_monitor.sources.uk_news.yahoo.client import (
            YahooNewsClient,
        )
        from investment_monitor.sources.uk_news.yahoo.connector import (
            _yahoo_symbol,
        )

        self.assertEqual(_yahoo_symbol("BP."), "BP.L")
        opener = FakeOpener((FIXTURES / "yahoo_vod.xml").read_bytes())
        connector = YahooNewsConnector(
            client=YahooNewsClient(opener=opener, requests_per_second=1000)
        )

        connector.collect(
            self.request(("BP.",), {"BP.": "uk"})
        )

        self.assertIn("s=BP.L", opener.requested[0])

    def test_failure_is_recorded(self) -> None:
        from investment_monitor.sources.uk_news.yahoo.client import (
            YahooNewsClient,
        )

        def failing_opener(request, timeout=None):
            raise YahooNewsRequestError("yahoo blocked")

        connector = YahooNewsConnector(
            client=YahooNewsClient(
                opener=failing_opener,
                requests_per_second=1000,
            )
        )

        with self.assertRaises(YahooNewsRequestError):
            connector.collect(
                self.request(("VOD",), {"VOD": "uk"})
            )

        self.assertEqual(len(connector.last_errors), 1)
        self.assertEqual(connector.last_errors[0][0], "VOD")


if __name__ == "__main__":
    unittest.main()
