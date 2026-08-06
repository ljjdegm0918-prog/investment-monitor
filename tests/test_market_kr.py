from datetime import date, datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from investment_monitor import (
    ALLOWED_MARKETS,
    CollectionRequest,
    FinnhubNewsConnector,
    InformationItem,
    MARKET_KR,
    SQLiteInformationRepository,
    WebRepository,
)


class MarketKRTests(unittest.TestCase):
    def test_market_kr_is_declared(self) -> None:
        self.assertEqual(MARKET_KR, "kr")
        self.assertIn("kr", ALLOWED_MARKETS)

    def test_collection_request_accepts_kr_market(self) -> None:
        request = CollectionRequest(
            tickers=("005930",),
            start_date=date(2026, 8, 1),
            end_date=date(2026, 8, 2),
            markets={"005930": "kr"},
        )

        self.assertEqual(request.market_for("005930"), "kr")

    def test_information_item_accepts_kr_market(self) -> None:
        item = InformationItem(
            source="news",
            source_type="news",
            external_id="kr-1",
            tickers=("005930",),
            issuer="005930",
            published_at=datetime(2026, 8, 1, tzinfo=timezone.utc),
            title="KR headline",
            document_type="news",
            url="https://example.test/kr-1",
            collected_at=datetime(2026, 8, 1, 12, tzinfo=timezone.utc),
            market="kr",
        )

        self.assertEqual(item.market, "kr")

    def test_invalid_market_is_still_rejected(self) -> None:
        with self.assertRaises(ValueError):
            CollectionRequest(
                tickers=("005930",),
                start_date=date(2026, 8, 1),
                end_date=date(2026, 8, 2),
                markets={"005930": "japan"},
            )
        with self.assertRaises(ValueError):
            InformationItem(
                source="news",
                source_type="news",
                external_id="bad",
                tickers=("005930",),
                issuer="005930",
                published_at=datetime(2026, 8, 1, tzinfo=timezone.utc),
                title="x",
                document_type="news",
                url="https://example.test/x",
                collected_at=datetime(2026, 8, 1, 12, tzinfo=timezone.utc),
                market="japan",
            )


class MarketKRWebTests(unittest.TestCase):
    class StubResolver:
        def resolve(self, ticker: str):
            return None

    def test_kr_company_is_added_as_unmapped(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            database_path = Path(temporary_directory) / "web.sqlite3"
            SQLiteInformationRepository(database_path)
            repository = WebRepository(database_path)

            result = repository.add_companies_batch(
                "005930",
                ("holdings",),
                self.StubResolver(),
                market="kr",
            )
            companies = repository.companies()

        self.assertEqual(len(result["added"]), 1)
        self.assertEqual(result["failed"], [])
        self.assertEqual(result["added"][0]["market"], "kr")
        self.assertEqual(result["added"][0]["mapping_status"], "unmapped")
        self.assertEqual(companies[0]["ticker"], "005930")
        self.assertEqual(companies[0]["market"], "kr")
        self.assertEqual(companies[0]["cik"], "")


class MarketKRFinnhubSkipTests(unittest.TestCase):
    def test_finnhub_skips_kr_without_http_requests(self) -> None:
        class ExplodingClient:
            def get_json(self, *args, **kwargs):
                raise AssertionError("KR must not trigger Finnhub requests")

        connector = FinnhubNewsConnector(client=ExplodingClient())

        items = connector.collect(
            CollectionRequest(
                tickers=("005930",),
                start_date=date(2026, 8, 1),
                end_date=date(2026, 8, 2),
                markets={"005930": "kr"},
            )
        )

        self.assertEqual(items, [])
        self.assertEqual(connector.last_errors, ())


if __name__ == "__main__":
    unittest.main()
