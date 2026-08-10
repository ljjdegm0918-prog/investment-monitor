from datetime import date, datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from investment_monitor import (
    ALLOWED_MARKETS,
    CollectionRequest,
    FinnhubNewsConnector,
    InformationItem,
    MARKET_TRQ,
    SQLiteInformationRepository,
    WebRepository,
)
from investment_monitor.registry import create_default_registry
from investment_monitor.web_repository import normalize_trq_ticker


class MarketTRQTests(unittest.TestCase):
    def test_market_trq_is_declared(self) -> None:
        self.assertEqual(MARKET_TRQ, "trq")
        self.assertIn("trq", ALLOWED_MARKETS)

    def test_no_virtual_alt_eu_market_codes(self) -> None:
        """TRQ-0 lock: the package must not get a virtual market code."""
        for blocked in ("aee", "eu", "eu_alt", "alt"):
            self.assertNotIn(blocked, ALLOWED_MARKETS)

    def test_collection_request_accepts_trq_market(self) -> None:
        request = CollectionRequest(
            tickers=("AZN",),
            start_date=date(2026, 8, 1),
            end_date=date(2026, 8, 2),
            markets={"AZN": "trq"},
        )

        self.assertEqual(request.market_for("AZN"), "trq")

    def test_information_item_accepts_trq_market(self) -> None:
        item = InformationItem(
            source="news",
            source_type="news",
            external_id="trq-1",
            tickers=("AZN",),
            issuer="AstraZeneca PLC",
            published_at=datetime(2026, 8, 1, tzinfo=timezone.utc),
            title="TRQ headline",
            document_type="news",
            url="https://example.test/trq-1",
            collected_at=datetime(2026, 8, 1, 12, tzinfo=timezone.utc),
            market="trq",
        )

        self.assertEqual(item.market, "trq")

    def test_invalid_market_is_still_rejected(self) -> None:
        with self.assertRaises(ValueError):
            CollectionRequest(
                tickers=("AZN",),
                start_date=date(2026, 8, 1),
                end_date=date(2026, 8, 2),
                markets={"AZN": "turquoise"},
            )


class MarketTRQTickerTests(unittest.TestCase):
    def test_normalize_trq_ticker_variants(self) -> None:
        for variant, expected in (
            ("AZN", "AZN"),
            ("azn", "AZN"),
            ("AZN.TRQ", "AZN"),
            ("SHEL TRQX", "SHEL"),
            ("VOD-TQEX", "VOD"),
            ("AZN.TRQ.TRQ", "AZN"),
            ("AZN-TQEX.TRQX", "AZN"),
            ("BARC", "BARC"),
        ):
            self.assertEqual(normalize_trq_ticker(variant), expected)

    def test_normalize_trq_ticker_keeps_plain_input(self) -> None:
        self.assertEqual(normalize_trq_ticker("VOD"), "VOD")
        self.assertEqual(normalize_trq_ticker("abcd"), "ABCD")

    def test_normalize_trq_ticker_does_not_erase_suffix_like_codes(self) -> None:
        self.assertEqual(normalize_trq_ticker("TRQ"), "TRQ")
        self.assertEqual(normalize_trq_ticker("TRQX"), "TRQX")
        self.assertEqual(normalize_trq_ticker("TQEX"), "TQEX")

    def test_normalize_trq_ticker_extracts_isin(self) -> None:
        self.assertEqual(normalize_trq_ticker("GB0009895292"), "GB0009895292")
        self.assertEqual(normalize_trq_ticker("gb0009895292"), "GB0009895292")
        self.assertEqual(
            normalize_trq_ticker("ISIN: DE0007164600 "), "DE0007164600"
        )


class MarketTRQWebTests(unittest.TestCase):
    def test_trq_company_is_added_as_unmapped_without_sec_resolver(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            database_path = Path(temporary_directory) / "web.sqlite3"
            SQLiteInformationRepository(database_path)
            repository = WebRepository(database_path)

            result = repository.add_companies_batch(
                "AZN.TRQ",
                ("holdings",),
                None,
                market="trq",
            )
            companies = repository.companies()

        self.assertEqual(len(result["added"]), 1)
        self.assertEqual(result["failed"], [])
        self.assertEqual(result["added"][0]["ticker"], "AZN")
        self.assertEqual(result["added"][0]["market"], "trq")
        self.assertEqual(result["added"][0]["mapping_status"], "unmapped")
        self.assertEqual(result["added"][0]["cik"], "")
        self.assertEqual(companies[0]["ticker"], "AZN")
        self.assertEqual(companies[0]["market"], "trq")

    def test_trq_ticker_variants_normalize_to_root(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            database_path = Path(temporary_directory) / "web.sqlite3"
            SQLiteInformationRepository(database_path)
            repository = WebRepository(database_path)

            result = repository.add_companies_batch(
                "AZN, AZN.TRQ, azn-trqx",
                ("holdings",),
                None,
                market="trq",
            )
            companies = repository.companies()

        self.assertEqual(len(result["added"]), 1)
        self.assertEqual(result["added"][0]["ticker"], "AZN")
        self.assertEqual(len(companies), 1)

    def test_filings_status_logic_survives_trq_company(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            database_path = Path(temporary_directory) / "web.sqlite3"
            SQLiteInformationRepository(database_path)
            repository = WebRepository(database_path)
            repository.add_companies_batch(
                "AZN",
                ("holdings",),
                None,
                market="trq",
            )

            statuses = repository.source_statuses(
                now=datetime(2026, 8, 2, 14, tzinfo=timezone.utc)
            )

        filings = next(
            record for record in statuses if record["type"] == "Filings"
        )
        self.assertEqual(filings["status"], "unavailable")


class MarketTRQFinnhubSkipTests(unittest.TestCase):
    def test_finnhub_skips_trq_without_http_requests(self) -> None:
        class ExplodingClient:
            def get_json(self, *args, **kwargs):
                raise AssertionError("TRQ must not trigger Finnhub requests")

        connector = FinnhubNewsConnector(client=ExplodingClient())

        items = connector.collect(
            CollectionRequest(
                tickers=("AZN",),
                start_date=date(2026, 8, 1),
                end_date=date(2026, 8, 2),
                markets={"AZN": "trq"},
            )
        )

        self.assertEqual(items, [])
        self.assertEqual(connector.last_errors, ())


class MarketTRQDisclosureLockTests(unittest.TestCase):
    def test_no_trq_disclosure_connector_is_registered_yet(self) -> None:
        """Lock the TRQ-1 spike decision until a key-free source lands.

        TRQ-1 re-test (2026-08-11): Turquoise is an LSEG MTF without an
        independent issuer OAM; the current official page is a JS-only
        LSE SPA (londonstockexchange.com/securities-trading/turquoise)
        with no server-rendered instrument/disclosure data, and the old
        LSEG reference-file CSV URLs return 404. No key-free Turquoise
        issuer announcement feed exists; no stock OAM is re-mapped onto
        market=trq. Remove this test when a real key-free Turquoise
        disclosure source lands.
        """
        registry = create_default_registry()

        names = registry.registered_names
        for blocked_name in (
            "turquoise_disclosure",
            "turquoise_oam",
            "trq_disclosure",
        ):
            self.assertNotIn(blocked_name, names)


if __name__ == "__main__":
    unittest.main()
