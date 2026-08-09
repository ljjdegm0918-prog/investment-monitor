from datetime import date, datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from investment_monitor import (
    ALLOWED_MARKETS,
    CollectionRequest,
    FinnhubNewsConnector,
    InformationItem,
    MARKET_TW,
    SQLiteInformationRepository,
    WebRepository,
)
from investment_monitor.web_repository import normalize_tw_ticker


class MarketTWTests(unittest.TestCase):
    def test_market_tw_is_declared(self) -> None:
        self.assertEqual(MARKET_TW, "tw")
        self.assertIn("tw", ALLOWED_MARKETS)

    def test_collection_request_accepts_tw_market(self) -> None:
        request = CollectionRequest(
            tickers=("2330",),
            start_date=date(2026, 8, 1),
            end_date=date(2026, 8, 2),
            markets={"2330": "tw"},
        )

        self.assertEqual(request.market_for("2330"), "tw")

    def test_information_item_accepts_tw_market(self) -> None:
        item = InformationItem(
            source="news",
            source_type="news",
            external_id="tw-1",
            tickers=("2330",),
            issuer="2330",
            published_at=datetime(2026, 8, 1, tzinfo=timezone.utc),
            title="TW headline",
            document_type="news",
            url="https://example.test/tw-1",
            collected_at=datetime(2026, 8, 1, 12, tzinfo=timezone.utc),
            market="tw",
        )

        self.assertEqual(item.market, "tw")

    def test_invalid_market_is_still_rejected(self) -> None:
        with self.assertRaises(ValueError):
            CollectionRequest(
                tickers=("2330",),
                start_date=date(2026, 8, 1),
                end_date=date(2026, 8, 2),
                markets={"2330": "japan"},
            )
        with self.assertRaises(ValueError):
            InformationItem(
                source="news",
                source_type="news",
                external_id="bad",
                tickers=("2330",),
                issuer="2330",
                published_at=datetime(2026, 8, 1, tzinfo=timezone.utc),
                title="x",
                document_type="news",
                url="https://example.test/x",
                collected_at=datetime(2026, 8, 1, 12, tzinfo=timezone.utc),
                market="japan",
            )


class MarketTWTickerTests(unittest.TestCase):
    def test_normalize_tw_ticker_variants(self) -> None:
        for variant in ("2330", "02330", "2330.TW", "2330.tw", "2330.TWO"):
            self.assertEqual(normalize_tw_ticker(variant), "2330")

    def test_normalize_tw_ticker_pads_short_codes(self) -> None:
        self.assertEqual(normalize_tw_ticker("700"), "0700")
        self.assertEqual(normalize_tw_ticker("0050"), "0050")

    def test_normalize_tw_ticker_keeps_non_numeric_input(self) -> None:
        self.assertEqual(normalize_tw_ticker("VOD"), "VOD")
        self.assertEqual(normalize_tw_ticker("VOD.TW"), "VOD.TW")


class MarketTWWebTests(unittest.TestCase):
    def test_tw_company_is_added_as_unmapped_without_sec_resolver(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            database_path = Path(temporary_directory) / "web.sqlite3"
            SQLiteInformationRepository(database_path)
            repository = WebRepository(database_path)

            result = repository.add_companies_batch(
                "2330",
                ("holdings",),
                None,
                market="tw",
            )
            companies = repository.companies()

        self.assertEqual(len(result["added"]), 1)
        self.assertEqual(result["failed"], [])
        self.assertEqual(result["added"][0]["ticker"], "2330")
        self.assertEqual(result["added"][0]["market"], "tw")
        self.assertEqual(result["added"][0]["mapping_status"], "unmapped")
        self.assertEqual(result["added"][0]["cik"], "")
        self.assertEqual(companies[0]["ticker"], "2330")
        self.assertEqual(companies[0]["market"], "tw")

    def test_tw_ticker_variants_normalize_to_four_digits(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            database_path = Path(temporary_directory) / "web.sqlite3"
            SQLiteInformationRepository(database_path)
            repository = WebRepository(database_path)

            result = repository.add_companies_batch(
                "2330, 02330, 2330.TW",
                ("holdings",),
                None,
                market="tw",
            )
            companies = repository.companies()

        self.assertEqual(len(result["added"]), 1)
        self.assertEqual(result["added"][0]["ticker"], "2330")
        self.assertEqual(len(companies), 1)

    def test_filings_status_logic_survives_tw_company(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            database_path = Path(temporary_directory) / "web.sqlite3"
            SQLiteInformationRepository(database_path)
            repository = WebRepository(database_path)
            repository.add_companies_batch(
                "2330",
                ("holdings",),
                None,
                market="tw",
            )

            statuses = repository.source_statuses(
                now=datetime(2026, 8, 2, 14, tzinfo=timezone.utc)
            )

        filings = next(
            record for record in statuses if record["type"] == "Filings"
        )
        self.assertEqual(filings["status"], "unavailable")


class MarketTWFinnhubSkipTests(unittest.TestCase):
    def test_finnhub_skips_tw_without_http_requests(self) -> None:
        class ExplodingClient:
            def get_json(self, *args, **kwargs):
                raise AssertionError("TW must not trigger Finnhub requests")

        connector = FinnhubNewsConnector(client=ExplodingClient())

        items = connector.collect(
            CollectionRequest(
                tickers=("2330",),
                start_date=date(2026, 8, 1),
                end_date=date(2026, 8, 2),
                markets={"2330": "tw"},
            )
        )

        self.assertEqual(items, [])
        self.assertEqual(connector.last_errors, ())


if __name__ == "__main__":
    unittest.main()
