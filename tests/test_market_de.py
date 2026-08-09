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


class MarketDETests(unittest.TestCase):
    def test_market_de_is_declared(self) -> None:
        self.assertEqual(MARKET_DE, "de")
        self.assertIn("de", ALLOWED_MARKETS)

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


if __name__ == "__main__":
    unittest.main()
