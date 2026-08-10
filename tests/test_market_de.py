from datetime import date, datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from investment_monitor import (
    ALLOWED_MARKETS,
    CollectionRequest,
    InformationItem,
    MARKET_DE,
    SQLiteInformationRepository,
    WebRepository,
)
from investment_monitor.web_repository import normalize_de_ticker
from investment_monitor.sources.news import FinnhubNewsConnector
from investment_monitor.sources.eqs_dgap import EqsDgapConnector
from investment_monitor.registry import create_default_registry
from investment_monitor.sources.de_news.google.client import (
    DEFAULT_BASE_URL as GOOGLE_DE_BASE_URL,
)
from investment_monitor.sources.de_news.google.connector import GoogleDeNewsConnector
from investment_monitor.sources.de_news.symbols import de_yahoo_symbol
from investment_monitor.sources.de_news.yahoo.client import (
    DEFAULT_BASE_URL as YAHOO_DE_BASE_URL,
)
from investment_monitor.sources.de_news.yahoo.connector import YahooDeNewsConnector


class MarketDETests(unittest.TestCase):
    def test_market_de_is_declared(self) -> None:
        self.assertEqual(MARKET_DE, "de")
        self.assertIn("de", ALLOWED_MARKETS)

    def test_german_etf_deepening_has_no_new_market_code(self) -> None:
        """DETF-0 lock: German ETF's stays on market=de."""
        for blocked in ("etf", "de_etf", "xetra_etf"):
            self.assertNotIn(blocked, ALLOWED_MARKETS)

    def test_collection_request_accepts_de_market(self) -> None:
        request = CollectionRequest(
            tickers=("SAP",),
            start_date=date(2026, 8, 1),
            end_date=date(2026, 8, 2),
            markets={"SAP": "de"},
        )

        self.assertEqual(request.market_for("SAP"), "de")

    def test_information_item_accepts_de_market(self) -> None:
        item = InformationItem(
            source="news",
            source_type="news",
            external_id="de-1",
            tickers=("SAP",),
            issuer="SAP",
            published_at=datetime(2026, 8, 1, tzinfo=timezone.utc),
            title="DE headline",
            document_type="news",
            url="https://example.test/de-1",
            collected_at=datetime(2026, 8, 1, 12, tzinfo=timezone.utc),
            market="de",
        )

        self.assertEqual(item.market, "de")

    def test_invalid_market_is_still_rejected(self) -> None:
        with self.assertRaises(ValueError):
            CollectionRequest(
                tickers=("SAP",),
                start_date=date(2026, 8, 1),
                end_date=date(2026, 8, 2),
                markets={"SAP": "germany"},
            )
        with self.assertRaises(ValueError):
            InformationItem(
                source="news",
                source_type="news",
                external_id="bad",
                tickers=("SAP",),
                issuer="SAP",
                published_at=datetime(2026, 8, 1, tzinfo=timezone.utc),
                title="x",
                document_type="news",
                url="https://example.test/x",
                collected_at=datetime(2026, 8, 1, 12, tzinfo=timezone.utc),
                market="germany",
            )


class MarketDETickerTests(unittest.TestCase):
    def test_normalize_de_ticker_variants(self) -> None:
        for variant, expected in (
            ("SAP", "SAP"),
            ("sap", "SAP"),
            ("SAP.DE", "SAP"),
            ("SAP.DE.DE", "SAP"),
            ("SAP.XETRA", "SAP"),
            ("SAP.XE", "SAP"),
            ("SAP.F", "SAP"),
            ("sap.xetra", "SAP"),
            ("SAP XETRA", "SAP"),
            ("SAP-F", "SAP"),
        ):
            self.assertEqual(normalize_de_ticker(variant), expected)

    def test_normalize_de_ticker_keeps_plain_input(self) -> None:
        self.assertEqual(normalize_de_ticker("VOD"), "VOD")
        self.assertEqual(normalize_de_ticker("abcd"), "ABCD")

    def test_normalize_de_ticker_keeps_bare_suffix_words(self) -> None:
        self.assertEqual(normalize_de_ticker("DE"), "DE")
        self.assertEqual(normalize_de_ticker("F"), "F")
        self.assertEqual(normalize_de_ticker("XE"), "XE")
        self.assertEqual(normalize_de_ticker("XETRA"), "XETRA")

    def test_normalize_de_ticker_extracts_isin(self) -> None:
        self.assertEqual(normalize_de_ticker("DE0007164600"), "DE0007164600")
        self.assertEqual(normalize_de_ticker("de0007164600"), "DE0007164600")
        self.assertEqual(
            normalize_de_ticker("ISIN: DE0007164600 "), "DE0007164600"
        )


class MarketDEWebTests(unittest.TestCase):
    def test_de_company_is_added_as_unmapped_without_sec_resolver(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            database_path = Path(temporary_directory) / "web.sqlite3"
            SQLiteInformationRepository(database_path)
            repository = WebRepository(database_path)

            result = repository.add_companies_batch(
                "SAP.DE",
                ("holdings",),
                None,
                market="de",
            )
            companies = repository.companies()

        self.assertEqual(len(result["added"]), 1)
        self.assertEqual(result["failed"], [])
        self.assertEqual(result["added"][0]["ticker"], "SAP")
        self.assertEqual(result["added"][0]["market"], "de")
        self.assertEqual(result["added"][0]["mapping_status"], "unmapped")
        self.assertEqual(result["added"][0]["cik"], "")
        self.assertEqual(companies[0]["ticker"], "SAP")
        self.assertEqual(companies[0]["market"], "de")

    def test_de_ticker_variants_normalize_to_root(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            database_path = Path(temporary_directory) / "web.sqlite3"
            SQLiteInformationRepository(database_path)
            repository = WebRepository(database_path)

            result = repository.add_companies_batch(
                "SAP, SAP.DE, sap-XETRA",
                ("holdings",),
                None,
                market="de",
            )
            companies = repository.companies()

        self.assertEqual(len(result["added"]), 1)
        self.assertEqual(result["added"][0]["ticker"], "SAP")
        self.assertEqual(len(companies), 1)


class MarketDEFinnhubSkipTests(unittest.TestCase):
    def test_finnhub_never_queries_de(self) -> None:
        class ExplodingClient:
            def get_json(self, *args, **kwargs):
                raise AssertionError("DE must not trigger Finnhub requests")

        connector = FinnhubNewsConnector(client=ExplodingClient())

        items = connector.collect(
            CollectionRequest(
                tickers=("SAP",),
                start_date=date(2026, 8, 1),
                end_date=date(2026, 8, 2),
                markets={"SAP": "de"},
            )
        )

        self.assertEqual(items, [])
        self.assertEqual(connector.last_errors, ())


class MarketDESourceRegistrationTests(unittest.TestCase):
    def test_de_sources_are_registered(self) -> None:
        registry = create_default_registry()
        for name in ("eqs_dgap", "yahoo_de", "google_news_de"):
            self.assertIn(name, registry.registered_names)
            self.assertIsNotNone(registry.factory_for(name))
        self.assertNotIn("de_community", registry.registered_names)

    def test_no_etf_specific_disclosure_sources_are_registered(self) -> None:
        """DETF-4 lock: no stable key-free German ETF-specific feed exists."""
        registry = create_default_registry()
        names = registry.registered_names
        for blocked in (
            "de_etf_prospectus",
            "bafin_fund",
            "eurex_etf",
            "xetra_etf_pack",
        ):
            self.assertNotIn(blocked, names)

    def test_de_yahoo_symbol_uses_dot_de_suffix(self) -> None:
        self.assertEqual(de_yahoo_symbol("SAP"), "SAP.DE")
        self.assertEqual(de_yahoo_symbol("sap.xetra"), "SAP.DE")

    def test_de_news_url_templates(self) -> None:
        self.assertTrue(YAHOO_DE_BASE_URL.startswith("https://"))
        self.assertTrue(GOOGLE_DE_BASE_URL.startswith("https://"))
        self.assertIn("feeds.finance.yahoo.com", YAHOO_DE_BASE_URL)
        self.assertIn("news.google.com", GOOGLE_DE_BASE_URL)

    def test_eqs_without_isin_records_honest_error(self) -> None:
        connector = EqsDgapConnector(universe={})
        items = connector.collect(
            CollectionRequest(
                tickers=("SAP",),
                start_date=date(2026, 8, 1),
                end_date=date(2026, 8, 2),
                markets={"SAP": "de"},
            )
        )
        self.assertEqual(items, [])
        self.assertEqual(connector.last_errors, (("SAP", "no_universe_isin"),))

    def test_de_news_connectors_skip_non_de_without_http(self) -> None:
        class ExplodingClient:
            def fetch_news(self, *args, **kwargs):
                raise AssertionError("non-DE market must not trigger news HTTP")

        request = CollectionRequest(
            tickers=("MC",),
            start_date=date(2026, 8, 1),
            end_date=date(2026, 8, 2),
            markets={"MC": "fr"},
        )

        yahoo_items = YahooDeNewsConnector(client=ExplodingClient()).collect(request)
        google_items = GoogleDeNewsConnector(client=ExplodingClient()).collect(request)

        self.assertEqual(yahoo_items, [])
        self.assertEqual(google_items, [])


if __name__ == "__main__":
    unittest.main()
