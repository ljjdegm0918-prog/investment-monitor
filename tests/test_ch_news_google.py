from datetime import date, datetime, timezone
from pathlib import Path
import unittest

from investment_monitor import (
    CollectionRequest,
    GoogleChNewsConnector,
    GoogleChNewsDataError,
    GoogleChNewsRequestError,
)
from investment_monitor.registry import create_default_registry


FIXTURES = Path(__file__).parent / "fixtures" / "ch_news"


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


class GoogleChClientTests(unittest.TestCase):
    def test_parses_rss_and_builds_switzerland_query(self) -> None:
        from investment_monitor.sources.ch_news.google.client import (
            GoogleChNewsClient,
            _parse_rss,
        )

        body = (FIXTURES / "google_ch_nesn.xml").read_bytes()
        records = _parse_rss(
            body,
            start_date=date(2026, 8, 1),
            end_date=date(2026, 8, 8),
        )

        self.assertEqual(len(records), 2)
        first = records[0]
        self.assertEqual(
            first["title"],
            "Nestle meldet starkes Quartalsergebnis",
        )
        self.assertEqual(
            first["published"],
            datetime(2026, 8, 5, 6, 0, tzinfo=timezone.utc),
        )

        opener = FakeOpener(body)
        client = GoogleChNewsClient(
            opener=opener,
            requests_per_second=1000,
        )
        fetched = client.fetch_news(
            "NESN.SW",
            date(2026, 8, 1),
            date(2026, 8, 8),
        )
        self.assertEqual(len(fetched), 2)
        self.assertIn("q=NESN.SW", opener.requested[0])
        self.assertIn("hl=de", opener.requested[0])
        self.assertIn("gl=CH", opener.requested[0])
        self.assertIn("ceid=CH:de", opener.requested[0])

    def test_malformed_feed_raises_data_error(self) -> None:
        from investment_monitor.sources.ch_news.google.client import _parse_rss

        with self.assertRaises(GoogleChNewsDataError):
            _parse_rss(
                b"<html><body>blocked</body></html>",
                start_date=date(2026, 8, 1),
                end_date=date(2026, 8, 8),
            )


class GoogleChConnectorTests(unittest.TestCase):
    def request(self, tickers, markets):
        return CollectionRequest(
            tickers=tickers,
            start_date=date(2026, 8, 1),
            end_date=date(2026, 8, 8),
            markets=markets,
        )

    def make_connector(self, symbol_for=None):
        from investment_monitor.sources.ch_news.google.client import (
            GoogleChNewsClient,
        )

        opener = FakeOpener((FIXTURES / "google_ch_nesn.xml").read_bytes())
        connector = GoogleChNewsConnector(
            client=GoogleChNewsClient(
                opener=opener,
                requests_per_second=1000,
            ),
            symbol_for=symbol_for,
        )
        return connector, opener

    def test_non_ch_markets_are_skipped_with_zero_http(self) -> None:
        connector, opener = self.make_connector()

        items = connector.collect(
            self.request(("AAPL", "VOD"), {"AAPL": "us", "VOD": "uk"})
        )

        self.assertEqual(items, [])
        self.assertEqual(connector.last_errors, ())
        self.assertEqual(opener.requested, [])

    def test_ch_maps_news_with_canonical_ticker(self) -> None:
        connector, opener = self.make_connector()

        items = connector.collect(
            self.request(("NESN.SW",), {"NESN.SW": "ch"})
        )

        self.assertEqual(len(items), 2)
        first = items[0]
        self.assertEqual(first.source, "google_news_ch")
        self.assertEqual(first.source_type, "news")
        self.assertEqual(first.tickers, ("NESN",))
        self.assertEqual(first.market, "ch")
        self.assertEqual(first.raw_metadata["provider"], "google_news_rss")
        self.assertEqual(first.raw_metadata["langs"], "de")
        self.assertIn("q=NESN.SW", opener.requested[0])

    def test_symbol_for_injection_is_used(self) -> None:
        connector, opener = self.make_connector(
            symbol_for=lambda code: f"{code}.TEST"
        )

        connector.collect(self.request(("NESN",), {"NESN": "ch"}))

        self.assertIn("q=NESN.TEST", opener.requested[0])

    def test_single_ticker_failure_raises_and_records_error(self) -> None:
        from investment_monitor.sources.ch_news.google.client import (
            GoogleChNewsClient,
        )

        def failing_opener(request, timeout=None):
            raise GoogleChNewsRequestError("google blocked")

        connector = GoogleChNewsConnector(
            client=GoogleChNewsClient(
                opener=failing_opener,
                requests_per_second=1000,
            )
        )

        with self.assertRaises(GoogleChNewsRequestError):
            connector.collect(self.request(("NESN",), {"NESN": "ch"}))

        self.assertEqual(len(connector.last_errors), 1)
        self.assertEqual(connector.last_errors[0][0], "NESN")

    def test_registry_registers_google_ch_without_secret_field(self) -> None:
        registry = create_default_registry()

        self.assertIsNotNone(registry.factory_for("google_news_ch"))
        self.assertEqual(registry.secret_fields_for("google_news_ch"), ())


if __name__ == "__main__":
    unittest.main()
