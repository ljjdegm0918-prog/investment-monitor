from datetime import date, datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from investment_monitor import (
    ALLOWED_MARKETS,
    CollectionRequest,
    FinnhubNewsConnector,
    InformationItem,
    MARKET_BE,
    SQLiteInformationRepository,
    WebRepository,
)
from investment_monitor.registry import create_default_registry
from investment_monitor.web_repository import normalize_be_ticker


class MarketBETests(unittest.TestCase):
    def test_market_be_is_declared(self) -> None:
        self.assertEqual(MARKET_BE, "be")
        self.assertIn("be", ALLOWED_MARKETS)

    def test_collection_request_accepts_be_market(self) -> None:
        request = CollectionRequest(
            tickers=("ABI",),
            start_date=date(2026, 8, 1),
            end_date=date(2026, 8, 2),
            markets={"ABI": "be"},
        )

        self.assertEqual(request.market_for("ABI"), "be")

    def test_information_item_accepts_be_market(self) -> None:
        item = InformationItem(
            source="news",
            source_type="news",
            external_id="be-1",
            tickers=("ABI",),
            issuer="ABI",
            published_at=datetime(2026, 8, 1, tzinfo=timezone.utc),
            title="BE headline",
            document_type="news",
            url="https://example.test/be-1",
            collected_at=datetime(2026, 8, 1, 12, tzinfo=timezone.utc),
            market="be",
        )

        self.assertEqual(item.market, "be")

    def test_invalid_market_is_still_rejected(self) -> None:
        with self.assertRaises(ValueError):
            CollectionRequest(
                tickers=("ABI",),
                start_date=date(2026, 8, 1),
                end_date=date(2026, 8, 2),
                markets={"ABI": "belgium"},
            )
        with self.assertRaises(ValueError):
            InformationItem(
                source="news",
                source_type="news",
                external_id="bad",
                tickers=("ABI",),
                issuer="ABI",
                published_at=datetime(2026, 8, 1, tzinfo=timezone.utc),
                title="x",
                document_type="news",
                url="https://example.test/x",
                collected_at=datetime(2026, 8, 1, 12, tzinfo=timezone.utc),
                market="belgium",
            )


class MarketBETickerTests(unittest.TestCase):
    def test_normalize_be_ticker_variants(self) -> None:
        for variant, expected in (
            ("ABI", "ABI"),
            ("ABI.BR", "ABI"),
            ("abi.br", "ABI"),
            ("ABI-BRU", "ABI"),
            ("ABI BRU", "ABI"),
            ("ABI.EBR", "ABI"),
            ("KBC.BR", "KBC"),
            ("SOLB.BR", "SOLB"),
            ("UCB.BR", "UCB"),
            ("ABI.BR.BR", "ABI"),
        ):
            self.assertEqual(normalize_be_ticker(variant), expected)

    def test_normalize_be_ticker_keeps_plain_input(self) -> None:
        self.assertEqual(normalize_be_ticker("VOD"), "VOD")
        self.assertEqual(normalize_be_ticker("abcd"), "ABCD")

    def test_normalize_be_ticker_does_not_erase_suffix_like_codes(self) -> None:
        self.assertEqual(normalize_be_ticker("BR"), "BR")
        self.assertEqual(normalize_be_ticker("BRU"), "BRU")
        self.assertEqual(normalize_be_ticker("EBR"), "EBR")
        self.assertEqual(normalize_be_ticker("A.BR"), "A")

    def test_normalize_be_ticker_extracts_isin(self) -> None:
        self.assertEqual(normalize_be_ticker("BE0003793107"), "BE0003793107")
        self.assertEqual(normalize_be_ticker("be0003565737"), "BE0003565737")
        self.assertEqual(
            normalize_be_ticker("ISIN: BE0003470755 "), "BE0003470755"
        )


class MarketBEWebTests(unittest.TestCase):
    def test_be_company_is_added_as_unmapped_without_sec_resolver(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            database_path = Path(temporary_directory) / "web.sqlite3"
            SQLiteInformationRepository(database_path)
            repository = WebRepository(database_path)

            result = repository.add_companies_batch(
                "ABI.BR",
                ("holdings",),
                None,
                market="be",
            )
            companies = repository.companies()

        self.assertEqual(len(result["added"]), 1)
        self.assertEqual(result["failed"], [])
        self.assertEqual(result["added"][0]["ticker"], "ABI")
        self.assertEqual(result["added"][0]["market"], "be")
        self.assertEqual(result["added"][0]["mapping_status"], "unmapped")
        self.assertEqual(result["added"][0]["cik"], "")
        self.assertEqual(companies[0]["ticker"], "ABI")
        self.assertEqual(companies[0]["market"], "be")

    def test_be_ticker_variants_normalize_to_root(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            database_path = Path(temporary_directory) / "web.sqlite3"
            SQLiteInformationRepository(database_path)
            repository = WebRepository(database_path)

            result = repository.add_companies_batch(
                "ABI, ABI.BR, abi-BRU",
                ("holdings",),
                None,
                market="be",
            )
            companies = repository.companies()

        self.assertEqual(len(result["added"]), 1)
        self.assertEqual(result["added"][0]["ticker"], "ABI")
        self.assertEqual(len(companies), 1)

    def test_filings_status_logic_survives_be_company(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            database_path = Path(temporary_directory) / "web.sqlite3"
            SQLiteInformationRepository(database_path)
            repository = WebRepository(database_path)
            repository.add_companies_batch(
                "ABI",
                ("holdings",),
                None,
                market="be",
            )

            statuses = repository.source_statuses(
                now=datetime(2026, 8, 2, 14, tzinfo=timezone.utc)
            )

        filings = next(
            record for record in statuses if record["type"] == "Filings"
        )
        self.assertEqual(filings["status"], "unavailable")


class MarketBEFinnhubSkipTests(unittest.TestCase):
    def test_finnhub_skips_be_without_http_requests(self) -> None:
        class ExplodingClient:
            def get_json(self, *args, **kwargs):
                raise AssertionError("BE must not trigger Finnhub requests")

        connector = FinnhubNewsConnector(client=ExplodingClient())

        items = connector.collect(
            CollectionRequest(
                tickers=("ABI",),
                start_date=date(2026, 8, 1),
                end_date=date(2026, 8, 2),
                markets={"ABI": "be"},
            )
        )

        self.assertEqual(items, [])
        self.assertEqual(connector.last_errors, ())


class MarketBEDisclosureFollowupTests(unittest.TestCase):
    def test_be_first_disclosure_source_still_registered(self) -> None:
        """Lock the BE-1 FSMA STORI connector in place."""
        registry = create_default_registry()

        self.assertIsNotNone(registry.factory_for("fsma_stori"))

    def test_no_paid_or_fake_be_disclosure_connector_is_registered(self) -> None:
        """Lock the BE-4 second-source boundary.

        BE-4 re-verified (2026-08-10): no stable key-free second Belgian
        disclosure source exists. Euronext Brussels announcements are
        Drupal HTML pages keyed by per-company node IDs (no RSS, no JSON
        export; ``_format=json`` returns 406); the key-free EQS News JSON
        API returns zero records for sampled Belgian ISINs including BEL 20
        names; paid feeds (Euronext Web Services/Saturn, FinancialReports.eu,
        LSEG) are excluded. Remove entries from the blocked list only when a
        real key-free source lands.
        """
        registry = create_default_registry()

        names = registry.registered_names
        for blocked_name in (
            "be_second_disclosure",
            "eqs_be",
            "euronext_be_announcements",
            "euronext_realtime",
            "financialreports_be",
            "lseg_be",
        ):
            self.assertNotIn(blocked_name, names)

        # The settings catalog still lists the unwired BE slot so the UI can
        # show Not implemented instead of implying a second source exists.
        from investment_monitor.config import load_settings

        catalog_names = {
            source.name
            for source in load_settings(Path("config/settings.yaml")).sources
        }
        self.assertIn("be_second_disclosure", catalog_names)


if __name__ == "__main__":
    unittest.main()
