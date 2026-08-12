from datetime import date, datetime, timezone
from pathlib import Path
import unittest

from investment_monitor import (
    CollectionRequest,
    GoogleEuxNewsConnector,
    GoogleEuxNewsDataError,
    GoogleEuxNewsRequestError,
)
from investment_monitor.registry import create_default_registry


FIXTURES = Path(__file__).parent / "fixtures" / "eux_news"


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


class GoogleEuxClientTests(unittest.TestCase):
    def test_parses_rss_and_builds_de_query(self) -> None:
        from investment_monitor.sources.eux_news.google.client import (
            GoogleEuxNewsClient,
            _parse_rss,
        )

        body = (FIXTURES / "google_eux_fdax.xml").read_bytes()
        records = _parse_rss(
            body,
            start_date=date(2026, 8, 1),
            end_date=date(2026, 8, 8),
        )

        self.assertEqual(len(records), 2)
        first = records[0]
        self.assertEqual(
            first["title"],
            "DAX Futures steigen vor Zinsentscheid",
        )
        self.assertEqual(
            first["published"],
            datetime(2026, 8, 5, 6, 0, tzinfo=timezone.utc),
        )

        opener = FakeOpener(body)
        client = GoogleEuxNewsClient(
            opener=opener,
            requests_per_second=1000,
        )
        fetched = client.fetch_news(
            '"DAX Futures"',
            date(2026, 8, 1),
            date(2026, 8, 8),
        )
        self.assertEqual(len(fetched), 2)
        self.assertIn("q=%22DAX%20Futures%22", opener.requested[0])
        self.assertIn("hl=de", opener.requested[0])
        self.assertIn("gl=DE", opener.requested[0])
        self.assertIn("ceid=DE:de", opener.requested[0])

    def test_malformed_feed_raises_data_error(self) -> None:
        from investment_monitor.sources.eux_news.google.client import _parse_rss

        with self.assertRaises(GoogleEuxNewsDataError):
            _parse_rss(
                b"<html><body>blocked</body></html>",
                start_date=date(2026, 8, 1),
                end_date=date(2026, 8, 8),
            )


class GoogleEuxConnectorTests(unittest.TestCase):
    def request(self, tickers, markets):
        return CollectionRequest(
            tickers=tickers,
            start_date=date(2026, 8, 1),
            end_date=date(2026, 8, 8),
            markets=markets,
        )

    def make_connector(self, name_for=None):
        from investment_monitor.sources.eux_news.google.client import (
            GoogleEuxNewsClient,
        )

        opener = FakeOpener((FIXTURES / "google_eux_fdax.xml").read_bytes())
        connector = GoogleEuxNewsConnector(
            client=GoogleEuxNewsClient(
                opener=opener,
                requests_per_second=1000,
            ),
            name_for=name_for,
        )
        return connector, opener

    def test_non_eux_markets_are_skipped_with_zero_http(self) -> None:
        connector, opener = self.make_connector()

        items = connector.collect(
            self.request(("AAPL", "FDAX"), {"AAPL": "us", "FDAX": "de"})
        )

        self.assertEqual(items, [])
        self.assertEqual(connector.last_errors, ())
        self.assertEqual(opener.requested, [])

    def test_eux_maps_news_with_canonical_code_and_name_query(self) -> None:
        connector, opener = self.make_connector(
            name_for=lambda code: "DAX Futures" if code == "FDAX" else None
        )

        items = connector.collect(
            self.request(("FDAX.EUX",), {"FDAX.EUX": "eux"})
        )

        self.assertEqual(len(items), 2)
        first = items[0]
        self.assertEqual(first.source, "google_news_eux")
        self.assertEqual(first.source_type, "news")
        self.assertEqual(first.tickers, ("FDAX",))
        self.assertEqual(first.market, "eux")
        self.assertEqual(first.raw_metadata["product_code"], "FDAX")
        self.assertEqual(first.raw_metadata["query"], '"DAX Futures"')
        self.assertIn("q=%22DAX%20Futures%22", opener.requested[0])

    def test_code_fallback_when_no_name_is_known(self) -> None:
        connector, opener = self.make_connector(name_for=lambda code: None)

        connector.collect(self.request(("FDAX",), {"FDAX": "eux"}))

        self.assertIn("q=FDAX", opener.requested[0])

    def test_single_ticker_failure_raises_and_records_error(self) -> None:
        from investment_monitor.sources.eux_news.google.client import (
            GoogleEuxNewsClient,
        )

        def failing_opener(request, timeout=None):
            raise GoogleEuxNewsRequestError("google blocked")

        connector = GoogleEuxNewsConnector(
            client=GoogleEuxNewsClient(
                opener=failing_opener,
                requests_per_second=1000,
            )
        )

        with self.assertRaises(GoogleEuxNewsRequestError):
            connector.collect(self.request(("FDAX",), {"FDAX": "eux"}))

        self.assertEqual(len(connector.last_errors), 1)
        self.assertEqual(connector.last_errors[0][0], "FDAX")

    def test_registry_registers_google_eux_without_secret_field(self) -> None:
        registry = create_default_registry()

        self.assertIsNotNone(registry.factory_for("google_news_eux"))
        self.assertEqual(registry.secret_fields_for("google_news_eux"), ())


if __name__ == "__main__":
    unittest.main()
