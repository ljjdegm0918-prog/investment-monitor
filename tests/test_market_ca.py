from datetime import date, datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from investment_monitor import (
    ALLOWED_MARKETS,
    CollectionRequest,
    FinnhubNewsConnector,
    InformationItem,
    MARKET_CA,
    SQLiteInformationRepository,
    WebRepository,
)
from investment_monitor.registry import create_default_registry
from investment_monitor.web_repository import infer_ca_board, normalize_ca_ticker


class MarketCATests(unittest.TestCase):
    def test_market_ca_is_declared(self) -> None:
        self.assertEqual(MARKET_CA, "ca")
        self.assertIn("ca", ALLOWED_MARKETS)

    def test_collection_request_accepts_ca_market(self) -> None:
        request = CollectionRequest(
            tickers=("RY",),
            start_date=date(2026, 8, 1),
            end_date=date(2026, 8, 2),
            markets={"RY": "ca"},
        )

        self.assertEqual(request.market_for("RY"), "ca")

    def test_information_item_accepts_ca_market(self) -> None:
        item = InformationItem(
            source="news",
            source_type="news",
            external_id="ca-1",
            tickers=("RY",),
            issuer="RY",
            published_at=datetime(2026, 8, 1, tzinfo=timezone.utc),
            title="CA headline",
            document_type="news",
            url="https://example.test/ca-1",
            collected_at=datetime(2026, 8, 1, 12, tzinfo=timezone.utc),
            market="ca",
        )

        self.assertEqual(item.market, "ca")

    def test_invalid_market_is_still_rejected(self) -> None:
        with self.assertRaises(ValueError):
            CollectionRequest(
                tickers=("RY",),
                start_date=date(2026, 8, 1),
                end_date=date(2026, 8, 2),
                markets={"RY": "japan"},
            )
        with self.assertRaises(ValueError):
            InformationItem(
                source="news",
                source_type="news",
                external_id="bad",
                tickers=("RY",),
                issuer="RY",
                published_at=datetime(2026, 8, 1, tzinfo=timezone.utc),
                title="x",
                document_type="news",
                url="https://example.test/x",
                collected_at=datetime(2026, 8, 1, 12, tzinfo=timezone.utc),
                market="japan",
            )


class MarketCATickerTests(unittest.TestCase):
    def test_normalize_ca_ticker_variants(self) -> None:
        for variant, expected in (
            ("RY", "RY"),
            ("RY.TO", "RY"),
            ("ry.to", "RY"),
            ("SHOP.TSX", "SHOP"),
            ("ABX.V", "ABX"),
            ("CVE.TSXV", "CVE"),
            ("X.CN", "X"),
            ("Q.NE", "Q"),
            ("HUT.NEO", "HUT"),
            ("RY-TO", "RY"),
            ("RY TO", "RY"),
        ):
            self.assertEqual(normalize_ca_ticker(variant), expected)

    def test_normalize_ca_ticker_keeps_plain_input(self) -> None:
        self.assertEqual(normalize_ca_ticker("VOD"), "VOD")
        self.assertEqual(normalize_ca_ticker("abcd"), "ABCD")

    def test_normalize_ca_ticker_does_not_erase_suffix_like_codes(self) -> None:
        self.assertEqual(normalize_ca_ticker("V"), "V")
        self.assertEqual(normalize_ca_ticker("TO"), "TO")
        self.assertEqual(normalize_ca_ticker("V.V"), "V")

    def test_infer_ca_board_from_suffix(self) -> None:
        for variant, expected in (
            ("RY.TO", "TSX"),
            ("SHOP.TSX", "TSX"),
            ("ABX.V", "TSXV"),
            ("CVE.TSXV", "TSXV"),
            ("X.CN", "CSE"),
            ("Q.NE", "NEO"),
            ("HUT.NEO", "NEO"),
            ("RY-TO", "TSX"),
            ("AUMB V", "TSXV"),
        ):
            self.assertEqual(infer_ca_board(variant), expected)
        self.assertIsNone(infer_ca_board("RY"))
        self.assertIsNone(infer_ca_board("TO"))


class MarketCAWebTests(unittest.TestCase):
    def test_ca_company_is_added_as_unmapped_without_sec_resolver(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            database_path = Path(temporary_directory) / "web.sqlite3"
            SQLiteInformationRepository(database_path)
            repository = WebRepository(database_path)

            result = repository.add_companies_batch(
                "RY.TO",
                ("holdings",),
                None,
                market="ca",
            )
            companies = repository.companies()

        self.assertEqual(len(result["added"]), 1)
        self.assertEqual(result["failed"], [])
        self.assertEqual(result["added"][0]["ticker"], "RY")
        self.assertEqual(result["added"][0]["market"], "ca")
        self.assertEqual(result["added"][0]["mapping_status"], "unmapped")
        self.assertEqual(result["added"][0]["cik"], "")
        self.assertEqual(result["added"][0]["exchange"], "TSX")
        self.assertEqual(companies[0]["ticker"], "RY")
        self.assertEqual(companies[0]["market"], "ca")
        self.assertEqual(companies[0]["exchange"], "TSX")

    def test_ca_board_inferred_from_suffix_without_universe(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            database_path = Path(temporary_directory) / "web.sqlite3"
            SQLiteInformationRepository(database_path)
            repository = WebRepository(database_path)

            result = repository.add_companies_batch(
                "AUMB.V, X.CN, HUT.NEO",
                ("watchlist",),
                None,
                market="ca",
            )

        by_ticker = {row["ticker"]: row for row in result["added"]}
        self.assertEqual(by_ticker["AUMB"]["exchange"], "TSXV")
        self.assertEqual(by_ticker["X"]["exchange"], "CSE")
        self.assertEqual(by_ticker["HUT"]["exchange"], "NEO")

    def test_ca_universe_board_wins_over_suffix_hint(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            database_path = Path(temporary_directory) / "web.sqlite3"
            SQLiteInformationRepository(database_path)
            repository = WebRepository(database_path)

            result = repository.add_companies_batch(
                "RY.V",
                ("holdings",),
                None,
                market="ca",
                name_fallback={
                    "RY": {
                        "name": "Royal Bank of Canada",
                        "exchange": "TSX",
                        "board": "TSX",
                    }
                },
            )

        self.assertEqual(result["added"][0]["exchange"], "TSX")
        self.assertEqual(result["added"][0]["name"], "Royal Bank of Canada")

    def test_ca_ticker_variants_normalize_to_root(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            database_path = Path(temporary_directory) / "web.sqlite3"
            SQLiteInformationRepository(database_path)
            repository = WebRepository(database_path)

            result = repository.add_companies_batch(
                "RY, RY.TO, ry.to",
                ("holdings",),
                None,
                market="ca",
            )
            companies = repository.companies()

        self.assertEqual(len(result["added"]), 1)
        self.assertEqual(result["added"][0]["ticker"], "RY")
        self.assertEqual(len(companies), 1)

    def test_filings_status_logic_survives_ca_company(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            database_path = Path(temporary_directory) / "web.sqlite3"
            SQLiteInformationRepository(database_path)
            repository = WebRepository(database_path)
            repository.add_companies_batch(
                "RY",
                ("holdings",),
                None,
                market="ca",
            )

            statuses = repository.source_statuses(
                now=datetime(2026, 8, 2, 14, tzinfo=timezone.utc)
            )

        filings = next(
            record for record in statuses if record["type"] == "Filings"
        )
        self.assertEqual(filings["status"], "unavailable")


class MarketCAFinnhubSkipTests(unittest.TestCase):
    def test_finnhub_skips_ca_without_http_requests(self) -> None:
        class ExplodingClient:
            def get_json(self, *args, **kwargs):
                raise AssertionError("CA must not trigger Finnhub requests")

        connector = FinnhubNewsConnector(client=ExplodingClient())

        items = connector.collect(
            CollectionRequest(
                tickers=("RY",),
                start_date=date(2026, 8, 1),
                end_date=date(2026, 8, 2),
                markets={"RY": "ca"},
            )
        )

        self.assertEqual(items, [])
        self.assertEqual(connector.last_errors, ())


class MarketCADisclosureStatusTests(unittest.TestCase):
    def test_free_ca_chain_is_registered_without_unblocking_sedar(self) -> None:
        """Wire reviewed IR/EDGAR fallbacks but keep SEDAR+ unwired."""
        registry = create_default_registry()

        names = registry.registered_names
        self.assertIn("ceoca_sedar", names)
        self.assertIn("ca_ir", names)
        self.assertIn("ca_edgar", names)
        self.assertIn("cse_filings", names)
        self.assertEqual(registry.factory_for("ceoca_sedar")().status, "partial")
        self.assertIn("CA_IR_CONFIG_PATH", registry.configuration_error_for("ca_ir"))
        self.assertIn(
            "CA_EDGAR_IDENTITY_PATH",
            registry.configuration_error_for("ca_edgar"),
        )
        self.assertIsNone(registry.configuration_error_for("cse_filings"))
        for blocked_name in ("sedar_plus", "sedarplus", "neo_filings"):
            self.assertNotIn(blocked_name, names)

        # Settings catalog still lists the unwired CA slots so the UI can
        # show Not implemented instead of implying full CA coverage.
        from investment_monitor.config import load_settings

        catalog_names = {
            source.name for source in load_settings(Path("config/settings.yaml")).sources
        }
        self.assertIn("sedar_plus", catalog_names)
        self.assertIn("cse_filings", catalog_names)
        self.assertIn("neo_filings", catalog_names)


if __name__ == "__main__":
    unittest.main()
