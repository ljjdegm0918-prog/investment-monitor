from datetime import date, datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from investment_monitor import (
    ALLOWED_MARKETS,
    CollectionRequest,
    FinnhubNewsConnector,
    InformationItem,
    MARKET_HK,
    SQLiteInformationRepository,
    WebRepository,
)


class MarketHKTests(unittest.TestCase):
    def test_market_hk_is_declared(self) -> None:
        self.assertEqual(MARKET_HK, "hk")
        self.assertIn("hk", ALLOWED_MARKETS)

    def test_collection_request_accepts_hk_market(self) -> None:
        request = CollectionRequest(
            tickers=("00700",),
            start_date=date(2026, 8, 1),
            end_date=date(2026, 8, 2),
            markets={"00700": "hk"},
        )

        self.assertEqual(request.market_for("00700"), "hk")

    def test_information_item_accepts_hk_market(self) -> None:
        item = InformationItem(
            source="news",
            source_type="news",
            external_id="hk-1",
            tickers=("00700",),
            issuer="00700",
            published_at=datetime(2026, 8, 1, tzinfo=timezone.utc),
            title="HK headline",
            document_type="news",
            url="https://example.test/hk-1",
            collected_at=datetime(2026, 8, 1, 12, tzinfo=timezone.utc),
            market="hk",
        )

        self.assertEqual(item.market, "hk")

    def test_invalid_market_is_still_rejected(self) -> None:
        with self.assertRaises(ValueError):
            CollectionRequest(
                tickers=("00700",),
                start_date=date(2026, 8, 1),
                end_date=date(2026, 8, 2),
                markets={"00700": "japan"},
            )
        with self.assertRaises(ValueError):
            InformationItem(
                source="news",
                source_type="news",
                external_id="bad",
                tickers=("00700",),
                issuer="00700",
                published_at=datetime(2026, 8, 1, tzinfo=timezone.utc),
                title="x",
                document_type="news",
                url="https://example.test/x",
                collected_at=datetime(2026, 8, 1, 12, tzinfo=timezone.utc),
                market="japan",
            )


class MarketHKWebTests(unittest.TestCase):
    def test_hk_company_is_added_as_unmapped_without_sec_resolver(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            database_path = Path(temporary_directory) / "web.sqlite3"
            SQLiteInformationRepository(database_path)
            repository = WebRepository(database_path)

            result = repository.add_companies_batch(
                "00700",
                ("holdings",),
                None,
                market="hk",
            )
            companies = repository.companies()

        self.assertEqual(len(result["added"]), 1)
        self.assertEqual(result["failed"], [])
        self.assertEqual(result["added"][0]["ticker"], "00700")
        self.assertEqual(result["added"][0]["market"], "hk")
        self.assertEqual(result["added"][0]["mapping_status"], "unmapped")
        self.assertEqual(result["added"][0]["cik"], "")
        self.assertEqual(companies[0]["ticker"], "00700")
        self.assertEqual(companies[0]["market"], "hk")
        self.assertEqual(companies[0]["cik"], "")

    def test_hk_ticker_variants_normalize_to_five_digits(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            database_path = Path(temporary_directory) / "web.sqlite3"
            SQLiteInformationRepository(database_path)
            repository = WebRepository(database_path)

            result = repository.add_companies_batch(
                "700, 0700, 00700, 0700.HK",
                ("holdings",),
                None,
                market="hk",
            )
            companies = repository.companies()

        self.assertEqual(len(result["added"]), 1)
        self.assertEqual(result["added"][0]["ticker"], "00700")
        self.assertEqual(result["added"][0]["market"], "hk")
        self.assertEqual(result["added"][0]["mapping_status"], "unmapped")
        self.assertEqual(len(companies), 1)
        self.assertEqual(companies[0]["ticker"], "00700")

    def test_filings_status_logic_survives_hk_company(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            database_path = Path(temporary_directory) / "web.sqlite3"
            SQLiteInformationRepository(database_path)
            repository = WebRepository(database_path)
            repository.add_companies_batch(
                "00700",
                ("holdings",),
                None,
                market="hk",
            )

            statuses = repository.source_statuses(
                now=datetime(2026, 8, 2, 14, tzinfo=timezone.utc)
            )

        filings = next(
            record for record in statuses if record["type"] == "Filings"
        )
        self.assertEqual(filings["status"], "unavailable")


class MarketHKFinnhubSkipTests(unittest.TestCase):
    def test_finnhub_skips_hk_without_http_requests(self) -> None:
        class ExplodingClient:
            def get_json(self, *args, **kwargs):
                raise AssertionError("HK must not trigger Finnhub requests")

        connector = FinnhubNewsConnector(client=ExplodingClient())

        items = connector.collect(
            CollectionRequest(
                tickers=("00700",),
                start_date=date(2026, 8, 1),
                end_date=date(2026, 8, 2),
                markets={"00700": "hk"},
            )
        )

        self.assertEqual(items, [])
        self.assertEqual(connector.last_errors, ())


if __name__ == "__main__":
    unittest.main()
