from datetime import date, datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from investment_monitor import (
    ALLOWED_MARKETS,
    CollectionRequest,
    FinnhubNewsConnector,
    InformationItem,
    MARKET_AQ,
    SQLiteInformationRepository,
    WebRepository,
)
from investment_monitor.registry import create_default_registry
from investment_monitor.web_repository import normalize_aq_ticker


class MarketAQTests(unittest.TestCase):
    def test_market_aq_is_declared(self) -> None:
        self.assertEqual(MARKET_AQ, "aq")
        self.assertIn("aq", ALLOWED_MARKETS)

    def test_collection_request_accepts_aq_market(self) -> None:
        request = CollectionRequest(
            tickers=("ADB",),
            start_date=date(2026, 8, 1),
            end_date=date(2026, 8, 2),
            markets={"ADB": "aq"},
        )

        self.assertEqual(request.market_for("ADB"), "aq")

    def test_information_item_accepts_aq_market(self) -> None:
        item = InformationItem(
            source="news",
            source_type="news",
            external_id="aq-1",
            tickers=("ADB",),
            issuer="ADB",
            published_at=datetime(2026, 8, 1, tzinfo=timezone.utc),
            title="AQ headline",
            document_type="news",
            url="https://example.test/aq-1",
            collected_at=datetime(2026, 8, 1, 12, tzinfo=timezone.utc),
            market="aq",
        )

        self.assertEqual(item.market, "aq")

    def test_invalid_market_is_still_rejected(self) -> None:
        with self.assertRaises(ValueError):
            CollectionRequest(
                tickers=("ADB",),
                start_date=date(2026, 8, 1),
                end_date=date(2026, 8, 2),
                markets={"ADB": "aquis"},
            )


class MarketAQTickerTests(unittest.TestCase):
    def test_normalize_aq_ticker_variants(self) -> None:
        for variant, expected in (
            ("ADB", "ADB"),
            ("adb", "ADB"),
            ("ADB.AQ", "ADB"),
            ("ADB AQ", "ADB"),
            ("ADB-AQ", "ADB"),
            ("ADB.AQ.AQ", "ADB"),
            ("ALSP.AQ", "ALSP"),
            ("DXSP.AQ", "DXSP"),
            ("MER", "MER"),
            ("HODL", "HODL"),
        ):
            self.assertEqual(normalize_aq_ticker(variant), expected)

    def test_normalize_aq_ticker_keeps_plain_input(self) -> None:
        self.assertEqual(normalize_aq_ticker("VOD"), "VOD")
        self.assertEqual(normalize_aq_ticker("abcd"), "ABCD")
        self.assertEqual(normalize_aq_ticker("B HODL"), "B HODL")

    def test_normalize_aq_ticker_does_not_erase_suffix_like_codes(self) -> None:
        self.assertEqual(normalize_aq_ticker("AQ"), "AQ")
        self.assertEqual(normalize_aq_ticker("aq"), "AQ")

    def test_normalize_aq_ticker_extracts_isin(self) -> None:
        self.assertEqual(normalize_aq_ticker("GB00BF01VL55"), "GB00BF01VL55")
        self.assertEqual(normalize_aq_ticker("gb00bf01vl55"), "GB00BF01VL55")
        self.assertEqual(
            normalize_aq_ticker("ISIN: GB00BF01VL55 "), "GB00BF01VL55"
        )
        self.assertEqual(normalize_aq_ticker("IE00BZ1T3V44"), "IE00BZ1T3V44")
        self.assertEqual(
            normalize_aq_ticker("GB0000075845.AQ"), "GB0000075845"
        )


class MarketAQWebTests(unittest.TestCase):
    def test_aq_company_is_added_as_unmapped_without_sec_resolver(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            database_path = Path(temporary_directory) / "web.sqlite3"
            SQLiteInformationRepository(database_path)
            repository = WebRepository(database_path)

            result = repository.add_companies_batch(
                "ADB.AQ",
                ("holdings",),
                None,
                market="aq",
            )
            companies = repository.companies()

        self.assertEqual(len(result["added"]), 1)
        self.assertEqual(result["failed"], [])
        self.assertEqual(result["added"][0]["ticker"], "ADB")
        self.assertEqual(result["added"][0]["market"], "aq")
        self.assertEqual(result["added"][0]["mapping_status"], "unmapped")
        self.assertEqual(result["added"][0]["cik"], "")
        self.assertEqual(companies[0]["ticker"], "ADB")
        self.assertEqual(companies[0]["market"], "aq")

    def test_aq_ticker_variants_normalize_to_root(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            database_path = Path(temporary_directory) / "web.sqlite3"
            SQLiteInformationRepository(database_path)
            repository = WebRepository(database_path)

            result = repository.add_companies_batch(
                "ADB, ADB.AQ, adb-aq",
                ("holdings",),
                None,
                market="aq",
            )
            companies = repository.companies()

        self.assertEqual(len(result["added"]), 1)
        self.assertEqual(result["added"][0]["ticker"], "ADB")
        self.assertEqual(len(companies), 1)

    def test_filings_status_logic_survives_aq_company(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            database_path = Path(temporary_directory) / "web.sqlite3"
            SQLiteInformationRepository(database_path)
            repository = WebRepository(database_path)
            repository.add_companies_batch(
                "ADB",
                ("holdings",),
                None,
                market="aq",
            )

            statuses = repository.source_statuses(
                now=datetime(2026, 8, 2, 14, tzinfo=timezone.utc)
            )

        filings = next(
            record for record in statuses if record["type"] == "Filings"
        )
        self.assertEqual(filings["status"], "unavailable")


class MarketAQFinnhubSkipTests(unittest.TestCase):
    def test_finnhub_skips_aq_without_http_requests(self) -> None:
        class ExplodingClient:
            def get_json(self, *args, **kwargs):
                raise AssertionError("AQ must not trigger Finnhub requests")

        connector = FinnhubNewsConnector(client=ExplodingClient())

        items = connector.collect(
            CollectionRequest(
                tickers=("ADB",),
                start_date=date(2026, 8, 1),
                end_date=date(2026, 8, 2),
                markets={"ADB": "aq"},
            )
        )

        self.assertEqual(items, [])
        self.assertEqual(connector.last_errors, ())


class MarketAQDisclosureLockTests(unittest.TestCase):
    def test_no_aq_disclosure_connector_is_registered_yet(self) -> None:
        """Lock the AQ-1 spike decision until a key-free source lands.

        AQ-1 spike (2026-08-10): the official AQSE announcements page
        (``www.aquis.eu/stock-exchange/announcements``) is a
        server-rendered HTML list (Date / Title / View rows), but the
        site sits behind a Vercel bot challenge (HTTP 429,
        ``X-Vercel-Mitigated: challenge``) that blocks stdlib/curl
        clients; ``embed.aquis.eu/api/*`` returns the same challenge,
        ``api.aquis.eu`` / ``data.aquis.eu`` abort TLS, and no key-free
        official JSON/RSS exists. No LSE/Investegate/uk-wire/Companies
        House source is used as an Aquis substitute and no paid Aquis
        data product is wired. Remove this test when a real key-free
        AQSE disclosure source lands.
        """
        registry = create_default_registry()

        names = registry.registered_names
        for blocked_name in (
            "aqse_announcements",
            "aquis_announcements",
            "investegate_aq",
            "uk_wire_aq",
            "aquis_datalink",
            "lse_paid",
        ):
            self.assertNotIn(blocked_name, names)


if __name__ == "__main__":
    unittest.main()
