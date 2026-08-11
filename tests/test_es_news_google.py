from datetime import date, datetime, timezone
from pathlib import Path
import unittest

from investment_monitor import (
    CollectionRequest,
    GoogleEsNewsConnector,
    GoogleEsNewsDataError,
    GoogleEsNewsRequestError,
)
from investment_monitor.registry import create_default_registry


FIXTURES = Path(__file__).parent / "fixtures" / "es_news"


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


class GoogleEsClientTests(unittest.TestCase):
    def test_parses_rss_and_builds_spain_query(self) -> None:
        from investment_monitor.sources.es_news.google.client import (
            GoogleEsNewsClient,
            _parse_rss,
        )

        body = (FIXTURES / "google_es_san.xml").read_bytes()
        records = _parse_rss(
            body,
            start_date=date(2026, 8, 1),
            end_date=date(2026, 8, 8),
        )

        self.assertEqual(len(records), 2)
        first = records[0]
        self.assertEqual(
            first["title"],
            "Santander amplia su programa de recompra",
        )
        self.assertEqual(
            first["published"],
            datetime(2026, 8, 5, 6, 0, tzinfo=timezone.utc),
        )

        opener = FakeOpener(body)
        client = GoogleEsNewsClient(
            opener=opener,
            requests_per_second=1000,
        )
        fetched = client.fetch_news(
            "SAN.MC",
            date(2026, 8, 1),
            date(2026, 8, 8),
        )
        self.assertEqual(len(fetched), 2)
        self.assertIn("q=SAN.MC", opener.requested[0])
        self.assertIn("hl=es", opener.requested[0])
        self.assertIn("gl=ES", opener.requested[0])
        self.assertIn("ceid=ES:es", opener.requested[0])

    def test_malformed_feed_raises_data_error(self) -> None:
        from investment_monitor.sources.es_news.google.client import _parse_rss

        with self.assertRaises(GoogleEsNewsDataError):
            _parse_rss(
                b"<html><body>blocked</body></html>",
                start_date=date(2026, 8, 1),
                end_date=date(2026, 8, 8),
            )


class GoogleEsConnectorTests(unittest.TestCase):
    def request(self, tickers, markets):
        return CollectionRequest(
            tickers=tickers,
            start_date=date(2026, 8, 1),
            end_date=date(2026, 8, 8),
            markets=markets,
        )

    def make_connector(self, symbol_for=None):
        from investment_monitor.sources.es_news.google.client import (
            GoogleEsNewsClient,
        )

        opener = FakeOpener((FIXTURES / "google_es_san.xml").read_bytes())
        connector = GoogleEsNewsConnector(
            client=GoogleEsNewsClient(
                opener=opener,
                requests_per_second=1000,
            ),
            symbol_for=symbol_for,
        )
        return connector, opener

    def test_non_es_markets_are_skipped_with_zero_http(self) -> None:
        connector, opener = self.make_connector()

        items = connector.collect(
            self.request(("AAPL", "VOD"), {"AAPL": "us", "VOD": "uk"})
        )

        self.assertEqual(items, [])
        self.assertEqual(connector.last_errors, ())
        self.assertEqual(opener.requested, [])

    def test_es_maps_news_with_canonical_ticker(self) -> None:
        connector, opener = self.make_connector()

        items = connector.collect(
            self.request(("SAN.MC",), {"SAN.MC": "es"})
        )

        self.assertEqual(len(items), 2)
        first = items[0]
        self.assertEqual(first.source, "google_news_es")
        self.assertEqual(first.source_type, "news")
        self.assertEqual(first.tickers, ("SAN",))
        self.assertEqual(first.market, "es")
        self.assertEqual(first.raw_metadata["provider"], "google_news_rss")
        self.assertEqual(first.raw_metadata["langs"], "es")
        self.assertIn("q=SAN.MC", opener.requested[0])

    def test_symbol_for_injection_is_used(self) -> None:
        connector, opener = self.make_connector(
            symbol_for=lambda code: f"{code}.TEST"
        )

        connector.collect(self.request(("SAN",), {"SAN": "es"}))

        self.assertIn("q=SAN.TEST", opener.requested[0])

    def test_single_ticker_failure_raises_and_records_error(self) -> None:
        from investment_monitor.sources.es_news.google.client import (
            GoogleEsNewsClient,
        )

        def failing_opener(request, timeout=None):
            raise GoogleEsNewsRequestError("google blocked")

        connector = GoogleEsNewsConnector(
            client=GoogleEsNewsClient(
                opener=failing_opener,
                requests_per_second=1000,
            )
        )

        with self.assertRaises(GoogleEsNewsRequestError):
            connector.collect(self.request(("SAN",), {"SAN": "es"}))

        self.assertEqual(len(connector.last_errors), 1)
        self.assertEqual(connector.last_errors[0][0], "SAN")

    def test_registry_registers_google_es_without_secret_field(self) -> None:
        registry = create_default_registry()

        self.assertIsNotNone(registry.factory_for("google_news_es"))
        self.assertEqual(registry.secret_fields_for("google_news_es"), ())


if __name__ == "__main__":
    unittest.main()
