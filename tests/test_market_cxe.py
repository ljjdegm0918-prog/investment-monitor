from datetime import date, datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from investment_monitor import (
    ALLOWED_MARKETS,
    CollectionRequest,
    FinnhubNewsConnector,
    InformationItem,
    MARKET_CXE,
    SQLiteInformationRepository,
    WebRepository,
)
from investment_monitor.registry import create_default_registry
from investment_monitor.web_repository import normalize_cxe_ticker


class MarketCXETests(unittest.TestCase):
    def test_market_cxe_is_declared(self) -> None:
        self.assertEqual(MARKET_CXE, "cxe")
        self.assertIn("cxe", ALLOWED_MARKETS)

    def test_no_virtual_alt_eu_market_codes(self) -> None:
        """AEE-0 lock: the package must not get a virtual market code."""
        for blocked in ("aee", "eu", "eu_alt", "alt"):
            self.assertNotIn(blocked, ALLOWED_MARKETS)

    def test_collection_request_accepts_cxe_market(self) -> None:
        request = CollectionRequest(
            tickers=("AZNL",),
            start_date=date(2026, 8, 1),
            end_date=date(2026, 8, 2),
            markets={"AZNL": "cxe"},
        )

        self.assertEqual(request.market_for("AZNL"), "cxe")

    def test_information_item_accepts_cxe_market(self) -> None:
        item = InformationItem(
            source="news",
            source_type="news",
            external_id="cxe-1",
            tickers=("AZNL",),
            issuer="AstraZeneca PLC",
            published_at=datetime(2026, 8, 1, tzinfo=timezone.utc),
            title="CXE headline",
            document_type="news",
            url="https://example.test/cxe-1",
            collected_at=datetime(2026, 8, 1, 12, tzinfo=timezone.utc),
            market="cxe",
        )

        self.assertEqual(item.market, "cxe")

    def test_invalid_market_is_still_rejected(self) -> None:
        with self.assertRaises(ValueError):
            CollectionRequest(
                tickers=("AZNL",),
                start_date=date(2026, 8, 1),
                end_date=date(2026, 8, 2),
                markets={"AZNL": "cboe"},
            )


class MarketCXETickerTests(unittest.TestCase):
    def test_normalize_cxe_ticker_variants(self) -> None:
        for variant, expected in (
            ("AZNl", "AZNL"),
            ("aznl", "AZNL"),
            ("AZNl.CXE", "AZNL"),
            ("SHELl", "SHELL"),
            ("ROPz", "ROPZ"),
            ("RRl", "RRL"),
            ("AZNl BXE", "AZNL"),
            ("AZNl-BXE.BXE", "AZNL"),
            ("JDWl", "JDWL"),
        ):
            self.assertEqual(normalize_cxe_ticker(variant), expected)

    def test_normalize_cxe_ticker_keeps_plain_input(self) -> None:
        self.assertEqual(normalize_cxe_ticker("VOD"), "VOD")
        self.assertEqual(normalize_cxe_ticker("abcd"), "ABCD")

    def test_normalize_cxe_ticker_does_not_erase_suffix_like_codes(self) -> None:
        self.assertEqual(normalize_cxe_ticker("CXE"), "CXE")
        self.assertEqual(normalize_cxe_ticker("BXE"), "BXE")

    def test_normalize_cxe_ticker_extracts_isin(self) -> None:
        self.assertEqual(normalize_cxe_ticker("GB0009895292"), "GB0009895292")
        self.assertEqual(normalize_cxe_ticker("gb0009895292"), "GB0009895292")
        self.assertEqual(
            normalize_cxe_ticker("ISIN: DE0007164600 "), "DE0007164600"
        )


class MarketCXEWebTests(unittest.TestCase):
    def test_cxe_company_is_added_as_unmapped_without_sec_resolver(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            database_path = Path(temporary_directory) / "web.sqlite3"
            SQLiteInformationRepository(database_path)
            repository = WebRepository(database_path)

            result = repository.add_companies_batch(
                "AZNl.CXE",
                ("holdings",),
                None,
                market="cxe",
            )
            companies = repository.companies()

        self.assertEqual(len(result["added"]), 1)
        self.assertEqual(result["failed"], [])
        self.assertEqual(result["added"][0]["ticker"], "AZNL")
        self.assertEqual(result["added"][0]["market"], "cxe")
        self.assertEqual(result["added"][0]["mapping_status"], "unmapped")
        self.assertEqual(result["added"][0]["cik"], "")
        self.assertEqual(companies[0]["ticker"], "AZNL")
        self.assertEqual(companies[0]["market"], "cxe")

    def test_cxe_ticker_variants_normalize_to_root(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            database_path = Path(temporary_directory) / "web.sqlite3"
            SQLiteInformationRepository(database_path)
            repository = WebRepository(database_path)

            result = repository.add_companies_batch(
                "AZNl, AZNL.CXE, aznl-bxe",
                ("holdings",),
                None,
                market="cxe",
            )
            companies = repository.companies()

        self.assertEqual(len(result["added"]), 1)
        self.assertEqual(result["added"][0]["ticker"], "AZNL")
        self.assertEqual(len(companies), 1)

    def test_filings_status_logic_survives_cxe_company(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            database_path = Path(temporary_directory) / "web.sqlite3"
            SQLiteInformationRepository(database_path)
            repository = WebRepository(database_path)
            repository.add_companies_batch(
                "AZNL",
                ("holdings",),
                None,
                market="cxe",
            )

            statuses = repository.source_statuses(
                now=datetime(2026, 8, 2, 14, tzinfo=timezone.utc)
            )

        filings = next(
            record for record in statuses if record["type"] == "Filings"
        )
        self.assertEqual(filings["status"], "unavailable")


class MarketCXEFinnhubSkipTests(unittest.TestCase):
    def test_finnhub_skips_cxe_without_http_requests(self) -> None:
        class ExplodingClient:
            def get_json(self, *args, **kwargs):
                raise AssertionError("CXE must not trigger Finnhub requests")

        connector = FinnhubNewsConnector(client=ExplodingClient())

        items = connector.collect(
            CollectionRequest(
                tickers=("AZNL",),
                start_date=date(2026, 8, 1),
                end_date=date(2026, 8, 2),
                markets={"AZNL": "cxe"},
            )
        )

        self.assertEqual(items, [])
        self.assertEqual(connector.last_errors, ())


class MarketCXEDisclosureLockTests(unittest.TestCase):
    def test_no_cxe_disclosure_connector_is_registered_yet(self) -> None:
        """Lock the AEE-1 spike decision until a key-free source lands.

        AEE-1 spike (2026-08-10): Cboe Europe is an MTF (BXE/CXE order
        books) without an independent issuer OAM; the official symbol /
        trade-data pages are venue data, not issuer disclosures, and no
        key-free issuer announcement feed exists for the books. Remove
        this test when a real key-free Cboe Europe disclosure source
        lands.
        """
        registry = create_default_registry()

        names = registry.registered_names
        for blocked_name in (
            "cboe_europe_disclosure",
            "cboe_europe_oam",
            "cxe_disclosure",
            "cboe_trade_data_filings",
            "turquoise_filings",
            "cboe_data_vantage",
            "lseg_mtf_paid",
        ):
            self.assertNotIn(blocked_name, names)


if __name__ == "__main__":
    unittest.main()
