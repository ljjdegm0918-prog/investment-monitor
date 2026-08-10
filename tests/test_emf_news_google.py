from datetime import date, datetime, timezone
from pathlib import Path
import unittest

from investment_monitor import (
    CollectionRequest,
    GoogleEmfNewsConnector,
    GoogleEmfNewsDataError,
    GoogleEmfNewsRequestError,
)
from investment_monitor.registry import create_default_registry


FIXTURES = Path(__file__).parent / "fixtures" / "emf_news"


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


class GoogleEmfClientTests(unittest.TestCase):
    def test_parses_rss_and_builds_gb_query(self) -> None:
        from investment_monitor.sources.emf_news.google.client import (
            GoogleEmfNewsClient,
            _parse_rss,
        )

        body = (FIXTURES / "google_emf_blackrock.xml").read_bytes()
        records = _parse_rss(
            body,
            start_date=date(2026, 8, 1),
            end_date=date(2026, 8, 8),
        )

        self.assertEqual(len(records), 2)
        first = records[0]
        self.assertEqual(
            first["title"],
            "BlackRock Global Allocation Fund updates factsheet",
        )
        self.assertEqual(
            first["published"],
            datetime(2026, 8, 5, 6, 0, tzinfo=timezone.utc),
        )

        opener = FakeOpener(body)
        client = GoogleEmfNewsClient(
            opener=opener,
            requests_per_second=1000,
        )
        fetched = client.fetch_news(
            '"BlackRock Global Allocation Fund"',
            date(2026, 8, 1),
            date(2026, 8, 8),
        )
        self.assertEqual(len(fetched), 2)
        self.assertIn(
            "q=%22BlackRock%20Global%20Allocation%20Fund%22",
            opener.requested[0],
        )
        self.assertIn("hl=en-GB", opener.requested[0])
        self.assertIn("gl=GB", opener.requested[0])
        self.assertIn("ceid=GB:en", opener.requested[0])

    def test_malformed_feed_raises_data_error(self) -> None:
        from investment_monitor.sources.emf_news.google.client import _parse_rss

        with self.assertRaises(GoogleEmfNewsDataError):
            _parse_rss(
                b"<html><body>blocked</body></html>",
                start_date=date(2026, 8, 1),
                end_date=date(2026, 8, 8),
            )


class GoogleEmfConnectorTests(unittest.TestCase):
    def request(self, tickers, markets):
        return CollectionRequest(
            tickers=tickers,
            start_date=date(2026, 8, 1),
            end_date=date(2026, 8, 8),
            markets=markets,
        )

    def make_connector(self, name_for=None):
        from investment_monitor.sources.emf_news.google.client import (
            GoogleEmfNewsClient,
        )

        opener = FakeOpener((FIXTURES / "google_emf_blackrock.xml").read_bytes())
        connector = GoogleEmfNewsConnector(
            client=GoogleEmfNewsClient(
                opener=opener,
                requests_per_second=1000,
            ),
            name_for=name_for,
        )
        return connector, opener

    def test_non_emf_markets_are_skipped_with_zero_http(self) -> None:
        connector, opener = self.make_connector()

        items = connector.collect(
            self.request(("AAPL", "AZNL"), {"AAPL": "us", "AZNL": "cxe"})
        )

        self.assertEqual(items, [])
        self.assertEqual(connector.last_errors, ())
        self.assertEqual(opener.requested, [])

    def test_emf_maps_news_with_canonical_isin_and_name_query(self) -> None:
        connector, opener = self.make_connector(
            name_for=lambda code: (
                "BlackRock Global Allocation Fund"
                if code == "LU0171254561"
                else None
            )
        )

        items = connector.collect(
            self.request(("LU0171254561.F",), {"LU0171254561.F": "emf"})
        )

        self.assertEqual(len(items), 2)
        first = items[0]
        self.assertEqual(first.source, "google_news_emf")
        self.assertEqual(first.source_type, "news")
        self.assertEqual(first.tickers, ("LU0171254561",))
        self.assertEqual(first.market, "emf")
        self.assertEqual(first.raw_metadata["fund_isin"], "LU0171254561")
        self.assertEqual(
            first.raw_metadata["query"],
            '"BlackRock Global Allocation Fund"',
        )
        self.assertIn(
            "q=%22BlackRock%20Global%20Allocation%20Fund%22",
            opener.requested[0],
        )

    def test_isin_fallback_when_no_name_is_known(self) -> None:
        connector, opener = self.make_connector(name_for=lambda code: None)

        connector.collect(
            self.request(("LU0171254561",), {"LU0171254561": "emf"})
        )

        self.assertIn("q=LU0171254561", opener.requested[0])

    def test_single_ticker_failure_raises_and_records_error(self) -> None:
        from investment_monitor.sources.emf_news.google.client import (
            GoogleEmfNewsClient,
        )

        def failing_opener(request, timeout=None):
            raise GoogleEmfNewsRequestError("google blocked")

        connector = GoogleEmfNewsConnector(
            client=GoogleEmfNewsClient(
                opener=failing_opener,
                requests_per_second=1000,
            )
        )

        with self.assertRaises(GoogleEmfNewsRequestError):
            connector.collect(
                self.request(("LU0171254561",), {"LU0171254561": "emf"})
            )

        self.assertEqual(len(connector.last_errors), 1)
        self.assertEqual(connector.last_errors[0][0], "LU0171254561")

    def test_registry_registers_google_emf_without_secret_field(self) -> None:
        registry = create_default_registry()

        self.assertIsNotNone(registry.factory_for("google_news_emf"))
        self.assertEqual(registry.secret_fields_for("google_news_emf"), ())


if __name__ == "__main__":
    unittest.main()
