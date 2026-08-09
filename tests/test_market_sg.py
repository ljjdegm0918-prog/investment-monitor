from datetime import date, datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from investment_monitor import (
    ALLOWED_MARKETS,
    CollectionRequest,
    FinnhubNewsConnector,
    InformationItem,
    MARKET_SG,
    SQLiteInformationRepository,
    WebRepository,
)
from investment_monitor.web_repository import normalize_sg_ticker


class MarketSGTests(unittest.TestCase):
    def test_market_sg_is_declared(self) -> None:
        self.assertEqual(MARKET_SG, "sg")
        self.assertIn("sg", ALLOWED_MARKETS)

    def test_collection_request_accepts_sg_market(self) -> None:
        request = CollectionRequest(
            tickers=("D05",),
            start_date=date(2026, 8, 1),
            end_date=date(2026, 8, 2),
            markets={"D05": "sg"},
        )

        self.assertEqual(request.market_for("D05"), "sg")

    def test_information_item_accepts_sg_market(self) -> None:
        item = InformationItem(
            source="news",
            source_type="news",
            external_id="sg-1",
            tickers=("D05",),
            issuer="D05",
            published_at=datetime(2026, 8, 1, tzinfo=timezone.utc),
            title="SG headline",
            document_type="news",
            url="https://example.test/sg-1",
            collected_at=datetime(2026, 8, 1, 12, tzinfo=timezone.utc),
            market="sg",
        )

        self.assertEqual(item.market, "sg")

    def test_invalid_market_is_still_rejected(self) -> None:
        with self.assertRaises(ValueError):
            CollectionRequest(
                tickers=("D05",),
                start_date=date(2026, 8, 1),
                end_date=date(2026, 8, 2),
                markets={"D05": "singapore"},
            )
        with self.assertRaises(ValueError):
            InformationItem(
                source="news",
                source_type="news",
                external_id="bad",
                tickers=("D05",),
                issuer="D05",
                published_at=datetime(2026, 8, 1, tzinfo=timezone.utc),
                title="x",
                document_type="news",
                url="https://example.test/x",
                collected_at=datetime(2026, 8, 1, 12, tzinfo=timezone.utc),
                market="singapore",
            )


class MarketSGTickerTests(unittest.TestCase):
    def test_normalize_sg_ticker_variants(self) -> None:
        for variant, expected in (
            ("D05", "D05"),
            ("D05.SI", "D05"),
            ("d05.si", "D05"),
            ("D05-SG", "D05"),
            ("D05 SG", "D05"),
            ("U11.SI", "U11"),
            ("C6L.SI", "C6L"),
            ("D05.SI.SI", "D05"),
            ("SE.SI", "SE"),
        ):
            self.assertEqual(normalize_sg_ticker(variant), expected)

    def test_normalize_sg_ticker_keeps_plain_input(self) -> None:
        self.assertEqual(normalize_sg_ticker("VOD"), "VOD")
        self.assertEqual(normalize_sg_ticker("abcd"), "ABCD")

    def test_normalize_sg_ticker_does_not_erase_suffix_like_codes(self) -> None:
        self.assertEqual(normalize_sg_ticker("SI"), "SI")
        self.assertEqual(normalize_sg_ticker("SG"), "SG")
        self.assertEqual(normalize_sg_ticker("A.SI"), "A")

    def test_normalize_sg_ticker_extracts_isin(self) -> None:
        self.assertEqual(normalize_sg_ticker("SG1J49008955"), "SG1J49008955")
        self.assertEqual(normalize_sg_ticker("sg1J49008955"), "SG1J49008955")
        self.assertEqual(
            normalize_sg_ticker("ISIN: SG1J49008955 "), "SG1J49008955"
        )


class MarketSGWebTests(unittest.TestCase):
    def test_sg_company_is_added_as_unmapped_without_sec_resolver(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            database_path = Path(temporary_directory) / "web.sqlite3"
            SQLiteInformationRepository(database_path)
            repository = WebRepository(database_path)

            result = repository.add_companies_batch(
                "D05.SI",
                ("holdings",),
                None,
                market="sg",
            )
            companies = repository.companies()

        self.assertEqual(len(result["added"]), 1)
        self.assertEqual(result["failed"], [])
        self.assertEqual(result["added"][0]["ticker"], "D05")
        self.assertEqual(result["added"][0]["market"], "sg")
        self.assertEqual(result["added"][0]["mapping_status"], "unmapped")
        self.assertEqual(result["added"][0]["cik"], "")
        self.assertEqual(companies[0]["ticker"], "D05")
        self.assertEqual(companies[0]["market"], "sg")

    def test_sg_ticker_variants_normalize_to_root(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            database_path = Path(temporary_directory) / "web.sqlite3"
            SQLiteInformationRepository(database_path)
            repository = WebRepository(database_path)

            result = repository.add_companies_batch(
                "D05, D05.SI, d05-SG",
                ("holdings",),
                None,
                market="sg",
            )
            companies = repository.companies()

        self.assertEqual(len(result["added"]), 1)
        self.assertEqual(result["added"][0]["ticker"], "D05")
        self.assertEqual(len(companies), 1)

    def test_filings_status_logic_survives_sg_company(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            database_path = Path(temporary_directory) / "web.sqlite3"
            SQLiteInformationRepository(database_path)
            repository = WebRepository(database_path)
            repository.add_companies_batch(
                "D05",
                ("holdings",),
                None,
                market="sg",
            )

            statuses = repository.source_statuses(
                now=datetime(2026, 8, 2, 14, tzinfo=timezone.utc)
            )

        filings = next(
            record for record in statuses if record["type"] == "Filings"
        )
        self.assertEqual(filings["status"], "unavailable")


class MarketSGFinnhubSkipTests(unittest.TestCase):
    def test_finnhub_skips_sg_without_http_requests(self) -> None:
        class ExplodingClient:
            def get_json(self, *args, **kwargs):
                raise AssertionError("SG must not trigger Finnhub requests")

        connector = FinnhubNewsConnector(client=ExplodingClient())

        items = connector.collect(
            CollectionRequest(
                tickers=("D05",),
                start_date=date(2026, 8, 1),
                end_date=date(2026, 8, 2),
                markets={"D05": "sg"},
            )
        )

        self.assertEqual(items, [])
        self.assertEqual(connector.last_errors, ())


if __name__ == "__main__":
    unittest.main()
