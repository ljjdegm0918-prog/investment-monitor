from datetime import date, datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from investment_monitor import (
    ALLOWED_MARKETS,
    CollectionRequest,
    FinnhubNewsConnector,
    InformationItem,
    MARKET_CA,
    SQLiteInformationRepository,
    WebRepository,
)
from investment_monitor.web_repository import normalize_ca_ticker


class MarketCATests(unittest.TestCase):
    def test_market_ca_is_declared(self) -> None:
        self.assertEqual(MARKET_CA, "ca")
        self.assertIn("ca", ALLOWED_MARKETS)

    def test_collection_request_accepts_ca_market(self) -> None:
        request = CollectionRequest(
            tickers=("RY",),
            start_date=date(2026, 8, 1),
            end_date=date(2026, 8, 2),
            markets={"RY": "ca"},
        )

        self.assertEqual(request.market_for("RY"), "ca")

    def test_information_item_accepts_ca_market(self) -> None:
        item = InformationItem(
            source="news",
            source_type="news",
            external_id="ca-1",
            tickers=("RY",),
            issuer="RY",
            published_at=datetime(2026, 8, 1, tzinfo=timezone.utc),
            title="CA headline",
            document_type="news",
            url="https://example.test/ca-1",
            collected_at=datetime(2026, 8, 1, 12, tzinfo=timezone.utc),
            market="ca",
        )

        self.assertEqual(item.market, "ca")

    def test_invalid_market_is_still_rejected(self) -> None:
        with self.assertRaises(ValueError):
            CollectionRequest(
                tickers=("RY",),
                start_date=date(2026, 8, 1),
                end_date=date(2026, 8, 2),
                markets={"RY": "japan"},
            )
        with self.assertRaises(ValueError):
            InformationItem(
                source="news",
                source_type="news",
                external_id="bad",
                tickers=("RY",),
                issuer="RY",
                published_at=datetime(2026, 8, 1, tzinfo=timezone.utc),
                title="x",
                document_type="news",
                url="https://example.test/x",
                collected_at=datetime(2026, 8, 1, 12, tzinfo=timezone.utc),
                market="japan",
            )


class MarketCATickerTests(unittest.TestCase):
    def test_normalize_ca_ticker_variants(self) -> None:
        for variant, expected in (
            ("RY", "RY"),
            ("RY.TO", "RY"),
            ("ry.to", "RY"),
            ("SHOP.TSX", "SHOP"),
            ("ABX.V", "ABX"),
            ("CVE.TSXV", "CVE"),
            ("X.CN", "X"),
            ("Q.NE", "Q"),
            ("HUT.NEO", "HUT"),
            ("RY-TO", "RY"),
            ("RY TO", "RY"),
        ):
            self.assertEqual(normalize_ca_ticker(variant), expected)

    def test_normalize_ca_ticker_keeps_plain_input(self) -> None:
        self.assertEqual(normalize_ca_ticker("VOD"), "VOD")
        self.assertEqual(normalize_ca_ticker("abcd"), "ABCD")

    def test_normalize_ca_ticker_does_not_erase_suffix_like_codes(self) -> None:
        self.assertEqual(normalize_ca_ticker("V"), "V")
        self.assertEqual(normalize_ca_ticker("TO"), "TO")
        self.assertEqual(normalize_ca_ticker("V.V"), "V")


class MarketCAWebTests(unittest.TestCase):
    def test_ca_company_is_added_as_unmapped_without_sec_resolver(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            database_path = Path(temporary_directory) / "web.sqlite3"
            SQLiteInformationRepository(database_path)
            repository = WebRepository(database_path)

            result = repository.add_companies_batch(
                "RY.TO",
                ("holdings",),
                None,
                market="ca",
            )
            companies = repository.companies()

        self.assertEqual(len(result["added"]), 1)
        self.assertEqual(result["failed"], [])
        self.assertEqual(result["added"][0]["ticker"], "RY")
        self.assertEqual(result["added"][0]["market"], "ca")
        self.assertEqual(result["added"][0]["mapping_status"], "unmapped")
        self.assertEqual(result["added"][0]["cik"], "")
        self.assertEqual(companies[0]["ticker"], "RY")
        self.assertEqual(companies[0]["market"], "ca")

    def test_ca_ticker_variants_normalize_to_root(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            database_path = Path(temporary_directory) / "web.sqlite3"
            SQLiteInformationRepository(database_path)
            repository = WebRepository(database_path)

            result = repository.add_companies_batch(
                "RY, RY.TO, ry.to",
                ("holdings",),
                None,
                market="ca",
            )
            companies = repository.companies()

        self.assertEqual(len(result["added"]), 1)
        self.assertEqual(result["added"][0]["ticker"], "RY")
        self.assertEqual(len(companies), 1)

    def test_filings_status_logic_survives_ca_company(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            database_path = Path(temporary_directory) / "web.sqlite3"
            SQLiteInformationRepository(database_path)
            repository = WebRepository(database_path)
            repository.add_companies_batch(
                "RY",
                ("holdings",),
                None,
                market="ca",
            )

            statuses = repository.source_statuses(
                now=datetime(2026, 8, 2, 14, tzinfo=timezone.utc)
            )

        filings = next(
            record for record in statuses if record["type"] == "Filings"
        )
        self.assertEqual(filings["status"], "unavailable")


class MarketCAFinnhubSkipTests(unittest.TestCase):
    def test_finnhub_skips_ca_without_http_requests(self) -> None:
        class ExplodingClient:
            def get_json(self, *args, **kwargs):
                raise AssertionError("CA must not trigger Finnhub requests")

        connector = FinnhubNewsConnector(client=ExplodingClient())

        items = connector.collect(
            CollectionRequest(
                tickers=("RY",),
                start_date=date(2026, 8, 1),
                end_date=date(2026, 8, 2),
                markets={"RY": "ca"},
            )
        )

        self.assertEqual(items, [])
        self.assertEqual(connector.last_errors, ())


if __name__ == "__main__":
    unittest.main()
