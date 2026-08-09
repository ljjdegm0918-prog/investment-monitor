from datetime import date, datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from investment_monitor import (
    ALLOWED_MARKETS,
    CollectionRequest,
    FinnhubNewsConnector,
    InformationItem,
    MARKET_ES,
    SQLiteInformationRepository,
    WebRepository,
)
from investment_monitor.web_repository import normalize_es_ticker


class MarketESTests(unittest.TestCase):
    def test_market_es_is_declared(self) -> None:
        self.assertEqual(MARKET_ES, "es")
        self.assertIn("es", ALLOWED_MARKETS)

    def test_collection_request_accepts_es_market(self) -> None:
        request = CollectionRequest(
            tickers=("SAN",),
            start_date=date(2026, 8, 1),
            end_date=date(2026, 8, 2),
            markets={"SAN": "es"},
        )

        self.assertEqual(request.market_for("SAN"), "es")

    def test_information_item_accepts_es_market(self) -> None:
        item = InformationItem(
            source="news",
            source_type="news",
            external_id="es-1",
            tickers=("SAN",),
            issuer="SAN",
            published_at=datetime(2026, 8, 1, tzinfo=timezone.utc),
            title="ES headline",
            document_type="news",
            url="https://example.test/es-1",
            collected_at=datetime(2026, 8, 1, 12, tzinfo=timezone.utc),
            market="es",
        )

        self.assertEqual(item.market, "es")

    def test_invalid_market_is_still_rejected(self) -> None:
        with self.assertRaises(ValueError):
            CollectionRequest(
                tickers=("SAN",),
                start_date=date(2026, 8, 1),
                end_date=date(2026, 8, 2),
                markets={"SAN": "spain"},
            )
        with self.assertRaises(ValueError):
            InformationItem(
                source="news",
                source_type="news",
                external_id="bad",
                tickers=("SAN",),
                issuer="SAN",
                published_at=datetime(2026, 8, 1, tzinfo=timezone.utc),
                title="x",
                document_type="news",
                url="https://example.test/x",
                collected_at=datetime(2026, 8, 1, 12, tzinfo=timezone.utc),
                market="spain",
            )


class MarketESTickerTests(unittest.TestCase):
    def test_normalize_es_ticker_variants(self) -> None:
        for variant, expected in (
            ("SAN", "SAN"),
            ("SAN.MC", "SAN"),
            ("san.mc", "SAN"),
            ("SAN-MAD", "SAN"),
            ("SAN MAD", "SAN"),
            ("TEF.MC", "TEF"),
            ("SAN-BME", "SAN"),
            ("SAN.MC.MC", "SAN"),
        ):
            self.assertEqual(normalize_es_ticker(variant), expected)

    def test_normalize_es_ticker_keeps_plain_input(self) -> None:
        self.assertEqual(normalize_es_ticker("VOD"), "VOD")
        self.assertEqual(normalize_es_ticker("abcd"), "ABCD")

    def test_normalize_es_ticker_does_not_erase_suffix_like_codes(self) -> None:
        self.assertEqual(normalize_es_ticker("MC"), "MC")
        self.assertEqual(normalize_es_ticker("MAD"), "MAD")
        self.assertEqual(normalize_es_ticker("BME"), "BME")
        self.assertEqual(normalize_es_ticker("A.MC"), "A")

    def test_normalize_es_ticker_extracts_isin(self) -> None:
        self.assertEqual(normalize_es_ticker("ES0113900J37"), "ES0113900J37")
        self.assertEqual(normalize_es_ticker("es0178430E18"), "ES0178430E18")
        self.assertEqual(
            normalize_es_ticker("ISIN: ES0113900J37 "), "ES0113900J37"
        )


class MarketESWebTests(unittest.TestCase):
    def test_es_company_is_added_as_unmapped_without_sec_resolver(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            database_path = Path(temporary_directory) / "web.sqlite3"
            SQLiteInformationRepository(database_path)
            repository = WebRepository(database_path)

            result = repository.add_companies_batch(
                "SAN.MC",
                ("holdings",),
                None,
                market="es",
            )
            companies = repository.companies()

        self.assertEqual(len(result["added"]), 1)
        self.assertEqual(result["failed"], [])
        self.assertEqual(result["added"][0]["ticker"], "SAN")
        self.assertEqual(result["added"][0]["market"], "es")
        self.assertEqual(result["added"][0]["mapping_status"], "unmapped")
        self.assertEqual(result["added"][0]["cik"], "")
        self.assertEqual(companies[0]["ticker"], "SAN")
        self.assertEqual(companies[0]["market"], "es")

    def test_es_ticker_variants_normalize_to_root(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            database_path = Path(temporary_directory) / "web.sqlite3"
            SQLiteInformationRepository(database_path)
            repository = WebRepository(database_path)

            result = repository.add_companies_batch(
                "SAN, SAN.MC, san-MAD",
                ("holdings",),
                None,
                market="es",
            )
            companies = repository.companies()

        self.assertEqual(len(result["added"]), 1)
        self.assertEqual(result["added"][0]["ticker"], "SAN")
        self.assertEqual(len(companies), 1)

    def test_filings_status_logic_survives_es_company(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            database_path = Path(temporary_directory) / "web.sqlite3"
            SQLiteInformationRepository(database_path)
            repository = WebRepository(database_path)
            repository.add_companies_batch(
                "SAN",
                ("holdings",),
                None,
                market="es",
            )

            statuses = repository.source_statuses(
                now=datetime(2026, 8, 2, 14, tzinfo=timezone.utc)
            )

        filings = next(
            record for record in statuses if record["type"] == "Filings"
        )
        self.assertEqual(filings["status"], "unavailable")


class MarketESFinnhubSkipTests(unittest.TestCase):
    def test_finnhub_skips_es_without_http_requests(self) -> None:
        class ExplodingClient:
            def get_json(self, *args, **kwargs):
                raise AssertionError("ES must not trigger Finnhub requests")

        connector = FinnhubNewsConnector(client=ExplodingClient())

        items = connector.collect(
            CollectionRequest(
                tickers=("SAN",),
                start_date=date(2026, 8, 1),
                end_date=date(2026, 8, 2),
                markets={"SAN": "es"},
            )
        )

        self.assertEqual(items, [])
        self.assertEqual(connector.last_errors, ())


if __name__ == "__main__":
    unittest.main()
