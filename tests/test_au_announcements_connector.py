from datetime import date, datetime, timezone
from pathlib import Path
import unittest

from investment_monitor import (
    AsxAnnouncementsClient,
    AsxAnnouncementsConnector,
    AsxAnnouncementsRequestError,
    CollectionRequest,
)
from investment_monitor.registry import create_default_registry


FIXTURES = Path(__file__).parent / "fixtures" / "au_announcements"


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


class AsxAnnouncementsConnectorTests(unittest.TestCase):
    def request(self, tickers, markets):
        return CollectionRequest(
            tickers=tickers,
            start_date=date(2026, 7, 1),
            end_date=date(2026, 7, 31),
            markets=markets,
        )

    def make_connector(self):
        opener = FakeOpener(
            (FIXTURES / "bhp_2026_archive.html").read_bytes()
        )
        connector = AsxAnnouncementsConnector(
            client=AsxAnnouncementsClient(
                opener=opener,
                requests_per_second=1000,
            )
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

    def test_au_maps_announcements_with_canonical_ticker(self) -> None:
        connector, opener = self.make_connector()

        items = connector.collect(
            self.request(("BHP.AX",), {"BHP.AX": "au"})
        )

        self.assertEqual(len(items), 2)
        self.assertIn("asxCode=BHP", opener.requested[0])
        self.assertIn("timeframe=Y", opener.requested[0])
        first = items[0]
        self.assertEqual(first.source, "asx_announcements")
        self.assertEqual(first.source_type, "regulatory_filing")
        self.assertEqual(first.tickers, ("BHP",))
        self.assertEqual(first.market, "au")
        self.assertEqual(first.document_type, "announcement")
        self.assertEqual(first.external_id, "03115448")
        self.assertEqual(
            first.raw_metadata["provider"],
            "asx_historical_announcements_archive",
        )
        self.assertEqual(
            first.raw_metadata["archive_coverage"],
            "complete_for_requested_years",
        )
        self.assertEqual(first.raw_metadata["is_price_sensitive"], True)
        self.assertEqual(
            first.url,
            "https://www.asx.com.au/asx/v2/statistics/"
            "displayAnnouncement.do?display=pdf&idsId=03115448",
        )

    def test_date_window_filters_old_items(self) -> None:
        connector, _ = self.make_connector()

        items = connector.collect(
            self.request(("BHP",), {"BHP": "au"})
        )

        self.assertEqual(len(items), 2)

    def test_single_ticker_failure_raises_and_records_error(self) -> None:
        from investment_monitor import AsxAnnouncementsClient

        def failing_opener(request, timeout=None):
            raise AsxAnnouncementsRequestError("asx blocked")

        connector = AsxAnnouncementsConnector(
            client=AsxAnnouncementsClient(
                opener=failing_opener,
                requests_per_second=1000,
            )
        )

        with self.assertRaises(AsxAnnouncementsRequestError):
            connector.collect(self.request(("BHP",), {"BHP": "au"}))

        self.assertEqual(len(connector.last_errors), 1)
        self.assertEqual(connector.last_errors[0][0], "BHP")

    def test_registry_registers_asx_announcements_without_secret_field(self) -> None:
        registry = create_default_registry()

        self.assertIsNotNone(registry.factory_for("asx_announcements"))
        self.assertEqual(registry.secret_fields_for("asx_announcements"), ())


if __name__ == "__main__":
    unittest.main()
