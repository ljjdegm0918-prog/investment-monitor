from datetime import date, datetime, timezone
from pathlib import Path
import unittest

from investment_monitor import (
    CollectionRequest,
    GoogleAuNewsConnector,
    GoogleAuNewsDataError,
    GoogleAuNewsRequestError,
)
from investment_monitor.registry import create_default_registry


FIXTURES = Path(__file__).parent / "fixtures" / "au_news"


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


class GoogleAuClientTests(unittest.TestCase):
    def test_parses_rss_and_builds_australia_query(self) -> None:
        from investment_monitor.sources.au_news.google.client import (
            GoogleAuNewsClient,
            _parse_rss,
        )

        body = (FIXTURES / "google_au_bhp.xml").read_bytes()
        records = _parse_rss(
            body,
            start_date=date(2026, 8, 1),
            end_date=date(2026, 8, 8),
        )

        self.assertEqual(len(records), 2)
        first = records[0]
        self.assertEqual(
            first["title"],
            "BHP, Rio Tinto executives to attend critical minerals summit",
        )
        self.assertEqual(
            first["published"],
            datetime(2026, 8, 7, 1, 39, tzinfo=timezone.utc),
        )

        opener = FakeOpener(body)
        client = GoogleAuNewsClient(
            opener=opener,
            requests_per_second=1000,
        )
        fetched = client.fetch_news(
            "BHP.AX",
            date(2026, 8, 1),
            date(2026, 8, 8),
        )
        self.assertEqual(len(fetched), 2)
        self.assertIn("q=BHP.AX", opener.requested[0])
        self.assertIn("hl=en-AU", opener.requested[0])
        self.assertIn("gl=AU", opener.requested[0])
        self.assertIn("ceid=AU:en", opener.requested[0])

    def test_malformed_feed_raises_data_error(self) -> None:
        from investment_monitor.sources.au_news.google.client import _parse_rss

        with self.assertRaises(GoogleAuNewsDataError):
            _parse_rss(
                b"<html><body>blocked</body></html>",
                start_date=date(2026, 8, 1),
                end_date=date(2026, 8, 8),
            )


class GoogleAuConnectorTests(unittest.TestCase):
    def request(self, tickers, markets):
        return CollectionRequest(
            tickers=tickers,
            start_date=date(2026, 8, 1),
            end_date=date(2026, 8, 8),
            markets=markets,
        )

    def make_connector(self, symbol_for=None):
        from investment_monitor.sources.au_news.google.client import (
            GoogleAuNewsClient,
        )

        opener = FakeOpener((FIXTURES / "google_au_bhp.xml").read_bytes())
        connector = GoogleAuNewsConnector(
            client=GoogleAuNewsClient(
                opener=opener,
                requests_per_second=1000,
            ),
            symbol_for=symbol_for,
        )
        return connector, opener

    def test_non_au_markets_are_skipped_with_zero_http(self) -> None:
        connector, opener = self.make_connector()

        items = connector.collect(
            self.request(("AAPL", "VOD"), {"AAPL": "us", "VOD": "uk"})
        )

        self.assertEqual(items, [])
        self.assertEqual(connector.last_errors, ())
        self.assertEqual(opener.requested, [])

    def test_au_maps_news_with_canonical_ticker(self) -> None:
        connector, opener = self.make_connector()

        items = connector.collect(
            self.request(("BHP.AX",), {"BHP.AX": "au"})
        )

        self.assertEqual(len(items), 2)
        first = items[0]
        self.assertEqual(first.source, "google_news_au")
        self.assertEqual(first.source_type, "news")
        self.assertEqual(first.tickers, ("BHP",))
        self.assertEqual(first.market, "au")
        self.assertEqual(first.raw_metadata["provider"], "google_news_rss")
        self.assertEqual(first.raw_metadata["langs"], "en")
        self.assertIn("q=BHP.AX", opener.requested[0])

    def test_symbol_for_injection_is_used(self) -> None:
        connector, opener = self.make_connector(
            symbol_for=lambda code: f"{code}.TEST"
        )

        connector.collect(self.request(("BHP",), {"BHP": "au"}))

        self.assertIn("q=BHP.TEST", opener.requested[0])

    def test_single_ticker_failure_raises_and_records_error(self) -> None:
        from investment_monitor.sources.au_news.google.client import (
            GoogleAuNewsClient,
        )

        def failing_opener(request, timeout=None):
            raise GoogleAuNewsRequestError("google blocked")

        connector = GoogleAuNewsConnector(
            client=GoogleAuNewsClient(
                opener=failing_opener,
                requests_per_second=1000,
            )
        )

        with self.assertRaises(GoogleAuNewsRequestError):
            connector.collect(self.request(("BHP",), {"BHP": "au"}))

        self.assertEqual(len(connector.last_errors), 1)
        self.assertEqual(connector.last_errors[0][0], "BHP")

    def test_registry_registers_google_au_without_secret_field(self) -> None:
        registry = create_default_registry()

        self.assertIsNotNone(registry.factory_for("google_news_au"))
        self.assertEqual(registry.secret_fields_for("google_news_au"), ())


if __name__ == "__main__":
    unittest.main()
