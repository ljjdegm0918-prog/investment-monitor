from datetime import date, datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from investment_monitor import (
    ALLOWED_MARKETS,
    CollectionRequest,
    FinnhubNewsConnector,
    InformationItem,
    MARKET_IT,
    SQLiteInformationRepository,
    WebRepository,
)
from investment_monitor.web_repository import normalize_it_ticker


class MarketITTests(unittest.TestCase):
    def test_market_it_is_declared(self) -> None:
        self.assertEqual(MARKET_IT, "it")
        self.assertIn("it", ALLOWED_MARKETS)

    def test_collection_request_accepts_it_market(self) -> None:
        request = CollectionRequest(
            tickers=("ENI",),
            start_date=date(2026, 8, 1),
            end_date=date(2026, 8, 2),
            markets={"ENI": "it"},
        )

        self.assertEqual(request.market_for("ENI"), "it")

    def test_information_item_accepts_it_market(self) -> None:
        item = InformationItem(
            source="news",
            source_type="news",
            external_id="it-1",
            tickers=("ENI",),
            issuer="ENI",
            published_at=datetime(2026, 8, 1, tzinfo=timezone.utc),
            title="IT headline",
            document_type="news",
            url="https://example.test/it-1",
            collected_at=datetime(2026, 8, 1, 12, tzinfo=timezone.utc),
            market="it",
        )

        self.assertEqual(item.market, "it")

    def test_invalid_market_is_still_rejected(self) -> None:
        with self.assertRaises(ValueError):
            CollectionRequest(
                tickers=("ENI",),
                start_date=date(2026, 8, 1),
                end_date=date(2026, 8, 2),
                markets={"ENI": "italy"},
            )
        with self.assertRaises(ValueError):
            InformationItem(
                source="news",
                source_type="news",
                external_id="bad",
                tickers=("ENI",),
                issuer="ENI",
                published_at=datetime(2026, 8, 1, tzinfo=timezone.utc),
                title="x",
                document_type="news",
                url="https://example.test/x",
                collected_at=datetime(2026, 8, 1, 12, tzinfo=timezone.utc),
                market="italy",
            )


class MarketITTickerTests(unittest.TestCase):
    def test_normalize_it_ticker_variants(self) -> None:
        for variant, expected in (
            ("ENI", "ENI"),
            ("ENI.MI", "ENI"),
            ("eni.mi", "ENI"),
            ("ENI-MIL", "ENI"),
            ("ENI MIL", "ENI"),
            ("UCG.MI", "UCG"),
            ("ENI-BIT", "ENI"),
            ("ENI.MI.MI", "ENI"),
        ):
            self.assertEqual(normalize_it_ticker(variant), expected)

    def test_normalize_it_ticker_keeps_plain_input(self) -> None:
        self.assertEqual(normalize_it_ticker("VOD"), "VOD")
        self.assertEqual(normalize_it_ticker("abcd"), "ABCD")

    def test_normalize_it_ticker_does_not_erase_suffix_like_codes(self) -> None:
        self.assertEqual(normalize_it_ticker("MI"), "MI")
        self.assertEqual(normalize_it_ticker("MIL"), "MIL")
        self.assertEqual(normalize_it_ticker("BIT"), "BIT")
        self.assertEqual(normalize_it_ticker("A.MI"), "A")

    def test_normalize_it_ticker_extracts_isin(self) -> None:
        self.assertEqual(normalize_it_ticker("IT0003132476"), "IT0003132476")
        self.assertEqual(normalize_it_ticker("it0000072618"), "IT0000072618")
        self.assertEqual(
            normalize_it_ticker("ISIN: IT0003132476 "), "IT0003132476"
        )


class MarketITWebTests(unittest.TestCase):
    def test_it_company_is_added_as_unmapped_without_sec_resolver(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            database_path = Path(temporary_directory) / "web.sqlite3"
            SQLiteInformationRepository(database_path)
            repository = WebRepository(database_path)

            result = repository.add_companies_batch(
                "ENI.MI",
                ("holdings",),
                None,
                market="it",
            )
            companies = repository.companies()

        self.assertEqual(len(result["added"]), 1)
        self.assertEqual(result["failed"], [])
        self.assertEqual(result["added"][0]["ticker"], "ENI")
        self.assertEqual(result["added"][0]["market"], "it")
        self.assertEqual(result["added"][0]["mapping_status"], "unmapped")
        self.assertEqual(result["added"][0]["cik"], "")
        self.assertEqual(companies[0]["ticker"], "ENI")
        self.assertEqual(companies[0]["market"], "it")

    def test_it_ticker_variants_normalize_to_root(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            database_path = Path(temporary_directory) / "web.sqlite3"
            SQLiteInformationRepository(database_path)
            repository = WebRepository(database_path)

            result = repository.add_companies_batch(
                "ENI, ENI.MI, eni-MIL",
                ("holdings",),
                None,
                market="it",
            )
            companies = repository.companies()

        self.assertEqual(len(result["added"]), 1)
        self.assertEqual(result["added"][0]["ticker"], "ENI")
        self.assertEqual(len(companies), 1)

    def test_filings_status_logic_survives_it_company(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            database_path = Path(temporary_directory) / "web.sqlite3"
            SQLiteInformationRepository(database_path)
            repository = WebRepository(database_path)
            repository.add_companies_batch(
                "ENI",
                ("holdings",),
                None,
                market="it",
            )

            statuses = repository.source_statuses(
                now=datetime(2026, 8, 2, 14, tzinfo=timezone.utc)
            )

        filings = next(
            record for record in statuses if record["type"] == "Filings"
        )
        self.assertEqual(filings["status"], "unavailable")


class MarketITFinnhubSkipTests(unittest.TestCase):
    def test_finnhub_skips_it_without_http_requests(self) -> None:
        class ExplodingClient:
            def get_json(self, *args, **kwargs):
                raise AssertionError("IT must not trigger Finnhub requests")

        connector = FinnhubNewsConnector(client=ExplodingClient())

        items = connector.collect(
            CollectionRequest(
                tickers=("ENI",),
                start_date=date(2026, 8, 1),
                end_date=date(2026, 8, 2),
                markets={"ENI": "it"},
            )
        )

        self.assertEqual(items, [])
        self.assertEqual(connector.last_errors, ())

if __name__ == "__main__":
    unittest.main()
