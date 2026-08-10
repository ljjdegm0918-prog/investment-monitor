from datetime import date, datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from investment_monitor import (
    ALLOWED_MARKETS,
    CollectionRequest,
    FinnhubNewsConnector,
    InformationItem,
    MARKET_EUX,
    SQLiteInformationRepository,
    WebRepository,
)
from investment_monitor.registry import create_default_registry
from investment_monitor.web_repository import normalize_eux_ticker


class MarketEUXTests(unittest.TestCase):
    def test_market_eux_is_declared(self) -> None:
        self.assertEqual(MARKET_EUX, "eux")
        self.assertIn("eux", ALLOWED_MARKETS)

    def test_no_over_broad_derivatives_market_codes(self) -> None:
        """EUX-0 lock: no over-broad futures/options code."""
        for blocked in ("fut", "opt", "deriv", "derivatives"):
            self.assertNotIn(blocked, ALLOWED_MARKETS)

    def test_collection_request_accepts_eux_market(self) -> None:
        request = CollectionRequest(
            tickers=("FDAX",),
            start_date=date(2026, 8, 1),
            end_date=date(2026, 8, 2),
            markets={"FDAX": "eux"},
        )

        self.assertEqual(request.market_for("FDAX"), "eux")

    def test_information_item_accepts_eux_market(self) -> None:
        item = InformationItem(
            source="news",
            source_type="news",
            external_id="eux-1",
            tickers=("FDAX",),
            issuer="DAX Futures",
            published_at=datetime(2026, 8, 1, tzinfo=timezone.utc),
            title="EUX headline",
            document_type="news",
            url="https://example.test/eux-1",
            collected_at=datetime(2026, 8, 1, 12, tzinfo=timezone.utc),
            market="eux",
        )

        self.assertEqual(item.market, "eux")

    def test_invalid_market_is_still_rejected(self) -> None:
        with self.assertRaises(ValueError):
            CollectionRequest(
                tickers=("FDAX",),
                start_date=date(2026, 8, 1),
                end_date=date(2026, 8, 2),
                markets={"FDAX": "eurex"},
            )


class MarketEUXTickerTests(unittest.TestCase):
    def test_normalize_eux_ticker_variants(self) -> None:
        for variant, expected in (
            ("FDAX", "FDAX"),
            ("fdax", "FDAX"),
            ("FDAX.EUX", "FDAX"),
            ("FGBL EUX", "FGBL"),
            ("ESX5-EUX", "ESX5"),
            ("FDAX.EUX.EUX", "FDAX"),
            ("2FE", "2FE"),
            ("34DF", "34DF"),
            ("OG7", "OG7"),
        ):
            self.assertEqual(normalize_eux_ticker(variant), expected)

    def test_normalize_eux_ticker_keeps_plain_input(self) -> None:
        self.assertEqual(normalize_eux_ticker("VOD"), "VOD")
        self.assertEqual(normalize_eux_ticker("abcd"), "ABCD")

    def test_normalize_eux_ticker_does_not_erase_suffix_like_codes(self) -> None:
        self.assertEqual(normalize_eux_ticker("EUX"), "EUX")

    def test_normalize_eux_ticker_extracts_isin(self) -> None:
        self.assertEqual(normalize_eux_ticker("DE0009652644"), "DE0009652644")
        self.assertEqual(normalize_eux_ticker("de0009652644"), "DE0009652644")
        self.assertEqual(
            normalize_eux_ticker("ISIN: DE000A1RRXJ7 "), "DE000A1RRXJ7"
        )


class MarketEUXWebTests(unittest.TestCase):
    def test_eux_product_is_added_as_unmapped_without_sec_resolver(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            database_path = Path(temporary_directory) / "web.sqlite3"
            SQLiteInformationRepository(database_path)
            repository = WebRepository(database_path)

            result = repository.add_companies_batch(
                "FDAX.EUX",
                ("holdings",),
                None,
                market="eux",
            )
            companies = repository.companies()

        self.assertEqual(len(result["added"]), 1)
        self.assertEqual(result["failed"], [])
        self.assertEqual(result["added"][0]["ticker"], "FDAX")
        self.assertEqual(result["added"][0]["market"], "eux")
        self.assertEqual(result["added"][0]["mapping_status"], "unmapped")
        self.assertEqual(result["added"][0]["cik"], "")
        self.assertEqual(companies[0]["ticker"], "FDAX")
        self.assertEqual(companies[0]["market"], "eux")

    def test_eux_ticker_variants_normalize_to_root(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            database_path = Path(temporary_directory) / "web.sqlite3"
            SQLiteInformationRepository(database_path)
            repository = WebRepository(database_path)

            result = repository.add_companies_batch(
                "FDAX, FDAX.EUX, fdax-eux",
                ("holdings",),
                None,
                market="eux",
            )
            companies = repository.companies()

        self.assertEqual(len(result["added"]), 1)
        self.assertEqual(result["added"][0]["ticker"], "FDAX")
        self.assertEqual(len(companies), 1)

    def test_filings_status_logic_survives_eux_product(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            database_path = Path(temporary_directory) / "web.sqlite3"
            SQLiteInformationRepository(database_path)
            repository = WebRepository(database_path)
            repository.add_companies_batch(
                "FDAX",
                ("holdings",),
                None,
                market="eux",
            )

            statuses = repository.source_statuses(
                now=datetime(2026, 8, 2, 14, tzinfo=timezone.utc)
            )

        filings = next(
            record for record in statuses if record["type"] == "Filings"
        )
        self.assertEqual(filings["status"], "unavailable")


class MarketEUXFinnhubSkipTests(unittest.TestCase):
    def test_finnhub_skips_eux_without_http_requests(self) -> None:
        class ExplodingClient:
            def get_json(self, *args, **kwargs):
                raise AssertionError("EUX must not trigger Finnhub requests")

        connector = FinnhubNewsConnector(client=ExplodingClient())

        items = connector.collect(
            CollectionRequest(
                tickers=("FDAX",),
                start_date=date(2026, 8, 1),
                end_date=date(2026, 8, 2),
                markets={"FDAX": "eux"},
            )
        )

        self.assertEqual(items, [])
        self.assertEqual(connector.last_errors, ())


class MarketEUXDisclosureLockTests(unittest.TestCase):
    def test_no_eux_disclosure_connector_is_registered_yet(self) -> None:
        """Lock the EUX-1 spike decision until a key-free source lands.

        EUX-1 spike (2026-08-11): Eurex circulars
        (``eurex.com/ex-en/find/circulars``) are a JS-driven search
        surface with no server-rendered per-product rows and no stable
        JSON feed; Eurex derivatives have no issuer OAM (products are
        exchange-listed contracts, not issuers). No circular connector is
        wired and no stock OAM (eqs_dgap / investegate / uk / de / cxe)
        is re-mapped onto market=eux. Remove this test when a real
        key-free per-product Eurex notice feed lands.
        """
        registry = create_default_registry()

        names = registry.registered_names
        for blocked_name in (
            "eurex_circulars",
            "eux_disclosure",
            "eux_circulars",
        ):
            self.assertNotIn(blocked_name, names)


if __name__ == "__main__":
    unittest.main()
