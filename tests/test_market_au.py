from datetime import date, datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from investment_monitor import (
    ALLOWED_MARKETS,
    CollectionRequest,
    FinnhubNewsConnector,
    InformationItem,
    MARKET_AU,
    SQLiteInformationRepository,
    WebRepository,
)
from investment_monitor.registry import create_default_registry
from investment_monitor.web_repository import normalize_au_ticker


class MarketAUTests(unittest.TestCase):
    def test_market_au_is_declared(self) -> None:
        self.assertEqual(MARKET_AU, "au")
        self.assertIn("au", ALLOWED_MARKETS)

    def test_collection_request_accepts_au_market(self) -> None:
        request = CollectionRequest(
            tickers=("BHP",),
            start_date=date(2026, 8, 1),
            end_date=date(2026, 8, 2),
            markets={"BHP": "au"},
        )

        self.assertEqual(request.market_for("BHP"), "au")

    def test_information_item_accepts_au_market(self) -> None:
        item = InformationItem(
            source="news",
            source_type="news",
            external_id="au-1",
            tickers=("BHP",),
            issuer="BHP",
            published_at=datetime(2026, 8, 1, tzinfo=timezone.utc),
            title="AU headline",
            document_type="news",
            url="https://example.test/au-1",
            collected_at=datetime(2026, 8, 1, 12, tzinfo=timezone.utc),
            market="au",
        )

        self.assertEqual(item.market, "au")

    def test_invalid_market_is_still_rejected(self) -> None:
        with self.assertRaises(ValueError):
            CollectionRequest(
                tickers=("BHP",),
                start_date=date(2026, 8, 1),
                end_date=date(2026, 8, 2),
                markets={"BHP": "japan"},
            )
        with self.assertRaises(ValueError):
            InformationItem(
                source="news",
                source_type="news",
                external_id="bad",
                tickers=("BHP",),
                issuer="BHP",
                published_at=datetime(2026, 8, 1, tzinfo=timezone.utc),
                title="x",
                document_type="news",
                url="https://example.test/x",
                collected_at=datetime(2026, 8, 1, 12, tzinfo=timezone.utc),
                market="japan",
            )


class MarketAUTickerTests(unittest.TestCase):
    def test_normalize_au_ticker_variants(self) -> None:
        for variant, expected in (
            ("BHP", "BHP"),
            ("BHP.AX", "BHP"),
            ("bhp.ax", "BHP"),
            ("BHP-ASX", "BHP"),
            ("BHP ASX", "BHP"),
            ("CBA.AX", "CBA"),
            ("BHP.AX.AX", "BHP"),
        ):
            self.assertEqual(normalize_au_ticker(variant), expected)

    def test_normalize_au_ticker_keeps_plain_input(self) -> None:
        self.assertEqual(normalize_au_ticker("VOD"), "VOD")
        self.assertEqual(normalize_au_ticker("abcd"), "ABCD")

    def test_normalize_au_ticker_does_not_erase_suffix_like_codes(self) -> None:
        self.assertEqual(normalize_au_ticker("AX"), "AX")
        self.assertEqual(normalize_au_ticker("ASX"), "ASX")
        self.assertEqual(normalize_au_ticker("A.AX"), "A")


class MarketAUWebTests(unittest.TestCase):
    def test_au_company_is_added_as_unmapped_without_sec_resolver(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            database_path = Path(temporary_directory) / "web.sqlite3"
            SQLiteInformationRepository(database_path)
            repository = WebRepository(database_path)

            result = repository.add_companies_batch(
                "BHP.AX",
                ("holdings",),
                None,
                market="au",
            )
            companies = repository.companies()

        self.assertEqual(len(result["added"]), 1)
        self.assertEqual(result["failed"], [])
        self.assertEqual(result["added"][0]["ticker"], "BHP")
        self.assertEqual(result["added"][0]["market"], "au")
        self.assertEqual(result["added"][0]["mapping_status"], "unmapped")
        self.assertEqual(result["added"][0]["cik"], "")
        self.assertEqual(companies[0]["ticker"], "BHP")
        self.assertEqual(companies[0]["market"], "au")

    def test_au_ticker_variants_normalize_to_root(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            database_path = Path(temporary_directory) / "web.sqlite3"
            SQLiteInformationRepository(database_path)
            repository = WebRepository(database_path)

            result = repository.add_companies_batch(
                "BHP, BHP.AX, bhp-ASX",
                ("holdings",),
                None,
                market="au",
            )
            companies = repository.companies()

        self.assertEqual(len(result["added"]), 1)
        self.assertEqual(result["added"][0]["ticker"], "BHP")
        self.assertEqual(len(companies), 1)

    def test_filings_status_logic_survives_au_company(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            database_path = Path(temporary_directory) / "web.sqlite3"
            SQLiteInformationRepository(database_path)
            repository = WebRepository(database_path)
            repository.add_companies_batch(
                "BHP",
                ("holdings",),
                None,
                market="au",
            )

            statuses = repository.source_statuses(
                now=datetime(2026, 8, 2, 14, tzinfo=timezone.utc)
            )

        filings = next(
            record for record in statuses if record["type"] == "Filings"
        )
        self.assertEqual(filings["status"], "unavailable")


class MarketAUFinnhubSkipTests(unittest.TestCase):
    def test_finnhub_skips_au_without_http_requests(self) -> None:
        class ExplodingClient:
            def get_json(self, *args, **kwargs):
                raise AssertionError("AU must not trigger Finnhub requests")

        connector = FinnhubNewsConnector(client=ExplodingClient())

        items = connector.collect(
            CollectionRequest(
                tickers=("BHP",),
                start_date=date(2026, 8, 1),
                end_date=date(2026, 8, 2),
                markets={"BHP": "au"},
            )
        )

        self.assertEqual(items, [])
        self.assertEqual(connector.last_errors, ())


class MarketAUDisclosureFollowupTests(unittest.TestCase):
    def test_asx_announcements_remains_registered(self) -> None:
        registry = create_default_registry()

        self.assertIsNotNone(registry.factory_for("asx_announcements"))

    def test_no_second_au_disclosure_connector_is_registered(self) -> None:
        """Lock the AU-4 D2 spike decision.

        AU-4 re-verified (2026-08-08) that the ASX announcements endpoint
        still returns only the latest 5 items with no pagination or deep
        document URL, and found no stable key-free second disclosure source
        (no ASX announcements RSS; ASIC has no keyless disclosure JSON). No
        second AU disclosure connector is registered. Remove this test when
        a real second source lands.
        """
        registry = create_default_registry()

        names = registry.registered_names
        for blocked_name in (
            "asx_rss",
            "asic_disclosure",
            "asx_announcements_rss",
        ):
            self.assertNotIn(blocked_name, names)


if __name__ == "__main__":
    unittest.main()
