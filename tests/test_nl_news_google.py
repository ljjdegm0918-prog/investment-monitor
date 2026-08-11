from datetime import date, datetime, timezone
from pathlib import Path
import unittest

from investment_monitor import (
    CollectionRequest,
    GoogleNlNewsConnector,
    GoogleNlNewsDataError,
    GoogleNlNewsRequestError,
)
from investment_monitor.registry import create_default_registry


FIXTURES = Path(__file__).parent / "fixtures" / "nl_news"


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


class GoogleNlClientTests(unittest.TestCase):
    def test_parses_rss_and_builds_netherlands_query(self) -> None:
        from investment_monitor.sources.nl_news.google.client import (
            GoogleNlNewsClient,
            _parse_rss,
        )

        body = (FIXTURES / "google_nl_asml.xml").read_bytes()
        records = _parse_rss(
            body,
            start_date=date(2026, 8, 1),
            end_date=date(2026, 8, 8),
        )

        self.assertEqual(len(records), 2)
        first = records[0]
        self.assertEqual(first["title"], "ASML investeert in nieuwe fabriek")
        self.assertEqual(
            first["published"],
            datetime(2026, 8, 5, 6, 0, tzinfo=timezone.utc),
        )

        opener = FakeOpener(body)
        client = GoogleNlNewsClient(
            opener=opener,
            requests_per_second=1000,
        )
        fetched = client.fetch_news(
            "ASML.AS",
            date(2026, 8, 1),
            date(2026, 8, 8),
        )
        self.assertEqual(len(fetched), 2)
        self.assertIn("q=ASML.AS", opener.requested[0])
        self.assertIn("hl=nl", opener.requested[0])
        self.assertIn("gl=NL", opener.requested[0])
        self.assertIn("ceid=NL:nl", opener.requested[0])

    def test_malformed_feed_raises_data_error(self) -> None:
        from investment_monitor.sources.nl_news.google.client import _parse_rss

        with self.assertRaises(GoogleNlNewsDataError):
            _parse_rss(
                b"<html><body>blocked</body></html>",
                start_date=date(2026, 8, 1),
                end_date=date(2026, 8, 8),
            )


class GoogleNlConnectorTests(unittest.TestCase):
    def request(self, tickers, markets):
        return CollectionRequest(
            tickers=tickers,
            start_date=date(2026, 8, 1),
            end_date=date(2026, 8, 8),
            markets=markets,
        )

    def make_connector(self, symbol_for=None):
        from investment_monitor.sources.nl_news.google.client import (
            GoogleNlNewsClient,
        )

        opener = FakeOpener((FIXTURES / "google_nl_asml.xml").read_bytes())
        connector = GoogleNlNewsConnector(
            client=GoogleNlNewsClient(
                opener=opener,
                requests_per_second=1000,
            ),
            symbol_for=symbol_for,
        )
        return connector, opener

    def test_non_nl_markets_are_skipped_with_zero_http(self) -> None:
        connector, opener = self.make_connector()

        items = connector.collect(
            self.request(("AAPL", "VOD"), {"AAPL": "us", "VOD": "uk"})
        )

        self.assertEqual(items, [])
        self.assertEqual(connector.last_errors, ())
        self.assertEqual(opener.requested, [])

    def test_nl_maps_news_with_canonical_ticker(self) -> None:
        connector, opener = self.make_connector()

        items = connector.collect(
            self.request(("ASML.AS",), {"ASML.AS": "nl"})
        )

        self.assertEqual(len(items), 2)
        first = items[0]
        self.assertEqual(first.source, "google_news_nl")
        self.assertEqual(first.source_type, "news")
        self.assertEqual(first.tickers, ("ASML",))
        self.assertEqual(first.market, "nl")
        self.assertEqual(first.raw_metadata["provider"], "google_news_rss")
        self.assertEqual(first.raw_metadata["langs"], "nl")
        self.assertIn("q=ASML.AS", opener.requested[0])

    def test_symbol_for_injection_is_used(self) -> None:
        connector, opener = self.make_connector(
            symbol_for=lambda code: f"{code}.TEST"
        )

        connector.collect(self.request(("ASML",), {"ASML": "nl"}))

        self.assertIn("q=ASML.TEST", opener.requested[0])

    def test_single_ticker_failure_raises_and_records_error(self) -> None:
        from investment_monitor.sources.nl_news.google.client import (
            GoogleNlNewsClient,
        )

        def failing_opener(request, timeout=None):
            raise GoogleNlNewsRequestError("google blocked")

        connector = GoogleNlNewsConnector(
            client=GoogleNlNewsClient(
                opener=failing_opener,
                requests_per_second=1000,
            )
        )

        with self.assertRaises(GoogleNlNewsRequestError):
            connector.collect(self.request(("ASML",), {"ASML": "nl"}))

        self.assertEqual(len(connector.last_errors), 1)
        self.assertEqual(connector.last_errors[0][0], "ASML")

    def test_registry_registers_google_nl_without_secret_field(self) -> None:
        registry = create_default_registry()

        self.assertIsNotNone(registry.factory_for("google_news_nl"))
        self.assertEqual(registry.secret_fields_for("google_news_nl"), ())


if __name__ == "__main__":
    unittest.main()
