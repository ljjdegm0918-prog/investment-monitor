from datetime import date, datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from investment_monitor import (
    ALLOWED_MARKETS,
    CollectionRequest,
    FinnhubNewsConnector,
    InformationItem,
    MARKET_UK,
    SQLiteInformationRepository,
    WebRepository,
)


class MarketUKTests(unittest.TestCase):
    def test_market_uk_is_declared(self) -> None:
        self.assertEqual(MARKET_UK, "uk")
        self.assertIn("uk", ALLOWED_MARKETS)

    def test_collection_request_accepts_uk_market(self) -> None:
        request = CollectionRequest(
            tickers=("VOD",),
            start_date=date(2026, 8, 1),
            end_date=date(2026, 8, 2),
            markets={"VOD": "uk"},
        )

        self.assertEqual(request.market_for("VOD"), "uk")

    def test_information_item_accepts_uk_market(self) -> None:
        item = InformationItem(
            source="news",
            source_type="news",
            external_id="uk-1",
            tickers=("VOD",),
            issuer="VOD",
            published_at=datetime(2026, 8, 1, tzinfo=timezone.utc),
            title="UK headline",
            document_type="news",
            url="https://example.test/uk-1",
            collected_at=datetime(2026, 8, 1, 12, tzinfo=timezone.utc),
            market="uk",
        )

        self.assertEqual(item.market, "uk")

    def test_invalid_market_is_still_rejected(self) -> None:
        with self.assertRaises(ValueError):
            CollectionRequest(
                tickers=("VOD",),
                start_date=date(2026, 8, 1),
                end_date=date(2026, 8, 2),
                markets={"VOD": "japan"},
            )
        with self.assertRaises(ValueError):
            InformationItem(
                source="news",
                source_type="news",
                external_id="bad",
                tickers=("VOD",),
                issuer="VOD",
                published_at=datetime(2026, 8, 1, tzinfo=timezone.utc),
                title="x",
                document_type="news",
                url="https://example.test/x",
                collected_at=datetime(2026, 8, 1, 12, tzinfo=timezone.utc),
                market="japan",
            )


class MarketUKWebTests(unittest.TestCase):
    def test_uk_company_is_added_as_unmapped_without_sec_resolver(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            database_path = Path(temporary_directory) / "web.sqlite3"
            SQLiteInformationRepository(database_path)
            repository = WebRepository(database_path)

            result = repository.add_companies_batch(
                "VOD",
                ("holdings",),
                None,
                market="uk",
            )
            companies = repository.companies()

        self.assertEqual(len(result["added"]), 1)
        self.assertEqual(result["failed"], [])
        self.assertEqual(result["added"][0]["ticker"], "VOD")
        self.assertEqual(result["added"][0]["market"], "uk")
        self.assertEqual(result["added"][0]["mapping_status"], "unmapped")
        self.assertEqual(result["added"][0]["cik"], "")
        self.assertEqual(companies[0]["ticker"], "VOD")
        self.assertEqual(companies[0]["market"], "uk")
        self.assertEqual(companies[0]["cik"], "")

    def test_dotted_lse_code_is_added_as_unmapped(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            database_path = Path(temporary_directory) / "web.sqlite3"
            SQLiteInformationRepository(database_path)
            repository = WebRepository(database_path)

            result = repository.add_companies_batch(
                "BP.",
                ("watchlist",),
                None,
                market="uk",
            )
            companies = repository.companies()

        self.assertEqual(len(result["added"]), 1)
        self.assertEqual(result["added"][0]["ticker"], "BP.")
        self.assertEqual(result["added"][0]["mapping_status"], "unmapped")
        self.assertEqual(companies[0]["ticker"], "BP.")

    def test_filings_status_logic_survives_uk_company(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            database_path = Path(temporary_directory) / "web.sqlite3"
            SQLiteInformationRepository(database_path)
            repository = WebRepository(database_path)
            repository.add_companies_batch(
                "VOD",
                ("holdings",),
                None,
                market="uk",
            )

            statuses = repository.source_statuses(
                now=datetime(2026, 8, 2, 14, tzinfo=timezone.utc)
            )

        filings = next(
            record for record in statuses if record["type"] == "Filings"
        )
        self.assertEqual(filings["status"], "unavailable")


class MarketUKFinnhubSkipTests(unittest.TestCase):
    def test_finnhub_skips_uk_without_http_requests(self) -> None:
        class ExplodingClient:
            def get_json(self, *args, **kwargs):
                raise AssertionError("UK must not trigger Finnhub requests")

        connector = FinnhubNewsConnector(client=ExplodingClient())

        items = connector.collect(
            CollectionRequest(
                tickers=("VOD",),
                start_date=date(2026, 8, 1),
                end_date=date(2026, 8, 2),
                markets={"VOD": "uk"},
            )
        )

        self.assertEqual(items, [])
        self.assertEqual(connector.last_errors, ())


if __name__ == "__main__":
    unittest.main()
