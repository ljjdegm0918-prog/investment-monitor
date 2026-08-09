from datetime import date, datetime, timezone
from pathlib import Path
import unittest

from investment_monitor import (
    CollectionRequest,
    GoogleItNewsConnector,
    GoogleItNewsDataError,
    GoogleItNewsRequestError,
)
from investment_monitor.registry import create_default_registry


FIXTURES = Path(__file__).parent / "fixtures" / "it_news"


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


class GoogleItClientTests(unittest.TestCase):
    def test_parses_rss_and_builds_italy_query(self) -> None:
        from investment_monitor.sources.it_news.google.client import (
            GoogleItNewsClient,
            _parse_rss,
        )

        body = (FIXTURES / "google_it_eni.xml").read_bytes()
        records = _parse_rss(
            body,
            start_date=date(2026, 8, 1),
            end_date=date(2026, 8, 8),
        )

        self.assertEqual(len(records), 2)
        first = records[0]
        self.assertEqual(first["title"], "Eni amplia il riacquisto di azioni")
        self.assertEqual(
            first["published"],
            datetime(2026, 8, 5, 6, 0, tzinfo=timezone.utc),
        )

        opener = FakeOpener(body)
        client = GoogleItNewsClient(
            opener=opener,
            requests_per_second=1000,
        )
        fetched = client.fetch_news(
            "ENI.MI",
            date(2026, 8, 1),
            date(2026, 8, 8),
        )
        self.assertEqual(len(fetched), 2)
        self.assertIn("q=ENI.MI", opener.requested[0])
        self.assertIn("hl=it", opener.requested[0])
        self.assertIn("gl=IT", opener.requested[0])
        self.assertIn("ceid=IT:it", opener.requested[0])

    def test_malformed_feed_raises_data_error(self) -> None:
        from investment_monitor.sources.it_news.google.client import _parse_rss

        with self.assertRaises(GoogleItNewsDataError):
            _parse_rss(
                b"<html><body>blocked</body></html>",
                start_date=date(2026, 8, 1),
                end_date=date(2026, 8, 8),
            )


class GoogleItConnectorTests(unittest.TestCase):
    def request(self, tickers, markets):
        return CollectionRequest(
            tickers=tickers,
            start_date=date(2026, 8, 1),
            end_date=date(2026, 8, 8),
            markets=markets,
        )

    def make_connector(self, symbol_for=None):
        from investment_monitor.sources.it_news.google.client import (
            GoogleItNewsClient,
        )

        opener = FakeOpener((FIXTURES / "google_it_eni.xml").read_bytes())
        connector = GoogleItNewsConnector(
            client=GoogleItNewsClient(
                opener=opener,
                requests_per_second=1000,
            ),
            symbol_for=symbol_for,
        )
        return connector, opener

    def test_non_it_markets_are_skipped_with_zero_http(self) -> None:
        connector, opener = self.make_connector()

        items = connector.collect(
            self.request(("AAPL", "VOD"), {"AAPL": "us", "VOD": "uk"})
        )

        self.assertEqual(items, [])
        self.assertEqual(connector.last_errors, ())
        self.assertEqual(opener.requested, [])

    def test_it_maps_news_with_canonical_ticker(self) -> None:
        connector, opener = self.make_connector()

        items = connector.collect(
            self.request(("ENI.MI",), {"ENI.MI": "it"})
        )

        self.assertEqual(len(items), 2)
        first = items[0]
        self.assertEqual(first.source, "google_news_it")
        self.assertEqual(first.source_type, "news")
        self.assertEqual(first.tickers, ("ENI",))
        self.assertEqual(first.market, "it")
        self.assertEqual(first.raw_metadata["provider"], "google_news_rss")
        self.assertEqual(first.raw_metadata["langs"], "it")
        self.assertIn("q=ENI.MI", opener.requested[0])

    def test_symbol_for_injection_is_used(self) -> None:
        connector, opener = self.make_connector(
            symbol_for=lambda code: f"{code}.TEST"
        )

        connector.collect(self.request(("ENI",), {"ENI": "it"}))

        self.assertIn("q=ENI.TEST", opener.requested[0])

    def test_single_ticker_failure_raises_and_records_error(self) -> None:
        from investment_monitor.sources.it_news.google.client import (
            GoogleItNewsClient,
        )

        def failing_opener(request, timeout=None):
            raise GoogleItNewsRequestError("google blocked")

        connector = GoogleItNewsConnector(
            client=GoogleItNewsClient(
                opener=failing_opener,
                requests_per_second=1000,
            )
        )

        with self.assertRaises(GoogleItNewsRequestError):
            connector.collect(self.request(("ENI",), {"ENI": "it"}))

        self.assertEqual(len(connector.last_errors), 1)
        self.assertEqual(connector.last_errors[0][0], "ENI")

    def test_registry_registers_google_it_without_secret_field(self) -> None:
        registry = create_default_registry()

        self.assertIsNotNone(registry.factory_for("google_news_it"))
        self.assertEqual(registry.secret_fields_for("google_news_it"), ())


if __name__ == "__main__":
    unittest.main()
