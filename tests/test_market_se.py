from datetime import date, datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from investment_monitor import (
    ALLOWED_MARKETS,
    CollectionRequest,
    FinnhubNewsConnector,
    InformationItem,
    MARKET_SE,
    SQLiteInformationRepository,
    WebRepository,
)
from investment_monitor.registry import create_default_registry
from investment_monitor.web_repository import normalize_se_ticker


class MarketSETests(unittest.TestCase):
    def test_market_se_is_declared(self) -> None:
        self.assertEqual(MARKET_SE, "se")
        self.assertIn("se", ALLOWED_MARKETS)

    def test_collection_request_accepts_se_market(self) -> None:
        request = CollectionRequest(
            tickers=("ERIC-B",),
            start_date=date(2026, 8, 1),
            end_date=date(2026, 8, 2),
            markets={"ERIC-B": "se"},
        )

        self.assertEqual(request.market_for("ERIC-B"), "se")

    def test_information_item_accepts_se_market(self) -> None:
        item = InformationItem(
            source="news",
            source_type="news",
            external_id="se-1",
            tickers=("ERIC-B",),
            issuer="ERIC-B",
            published_at=datetime(2026, 8, 1, tzinfo=timezone.utc),
            title="SE headline",
            document_type="news",
            url="https://example.test/se-1",
            collected_at=datetime(2026, 8, 1, 12, tzinfo=timezone.utc),
            market="se",
        )

        self.assertEqual(item.market, "se")

    def test_invalid_market_is_still_rejected(self) -> None:
        with self.assertRaises(ValueError):
            CollectionRequest(
                tickers=("ERIC-B",),
                start_date=date(2026, 8, 1),
                end_date=date(2026, 8, 2),
                markets={"ERIC-B": "sweden"},
            )


class MarketSETickerTests(unittest.TestCase):
    def test_normalize_se_ticker_variants(self) -> None:
        for variant, expected in (
            ("ERIC-B", "ERIC-B"),
            ("eric-b", "ERIC-B"),
            ("ERIC-B.ST", "ERIC-B"),
            ("ERIC-B.STO", "ERIC-B"),
            ("ERIC-B-OMX", "ERIC-B"),
            ("ERIC B ST", "ERIC B"),
            ("ERIC-B.ST.ST", "ERIC-B"),
            ("VOLV-B", "VOLV-B"),
            ("volv-b.st", "VOLV-B"),
            ("SEB-A", "SEB-A"),
            ("ATB", "ATB"),
            ("ATLAS-B", "ATLAS-B"),
        ):
            self.assertEqual(normalize_se_ticker(variant), expected)

    def test_normalize_se_ticker_keeps_plain_input(self) -> None:
        self.assertEqual(normalize_se_ticker("VOD"), "VOD")
        self.assertEqual(normalize_se_ticker("abcd"), "ABCD")

    def test_normalize_se_ticker_does_not_erase_suffix_like_codes(self) -> None:
        self.assertEqual(normalize_se_ticker("ST"), "ST")
        self.assertEqual(normalize_se_ticker("STO"), "STO")
        self.assertEqual(normalize_se_ticker("OMX"), "OMX")
        self.assertEqual(normalize_se_ticker("B"), "B")

    def test_normalize_se_ticker_preserves_share_classes(self) -> None:
        # A share-class letter after a hyphen is never treated as an
        # exchange suffix: ERIC-B / VOLV-B / SEB-A must stay intact.
        self.assertEqual(normalize_se_ticker("ERIC-B"), "ERIC-B")
        self.assertEqual(normalize_se_ticker("VOLV-B.ST"), "VOLV-B")
        self.assertEqual(normalize_se_ticker("SEB-A.STO"), "SEB-A")

    def test_normalize_se_ticker_extracts_isin(self) -> None:
        self.assertEqual(normalize_se_ticker("SE0000108656"), "SE0000108656")
        self.assertEqual(normalize_se_ticker("se0000108656"), "SE0000108656")
        self.assertEqual(
            normalize_se_ticker("ISIN: SE0000108656 "), "SE0000108656"
        )


class MarketSEWebTests(unittest.TestCase):
    def test_se_company_is_added_as_unmapped_without_sec_resolver(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            database_path = Path(temporary_directory) / "web.sqlite3"
            SQLiteInformationRepository(database_path)
            repository = WebRepository(database_path)

            result = repository.add_companies_batch(
                "ERIC-B.ST",
                ("holdings",),
                None,
                market="se",
            )
            companies = repository.companies()

        self.assertEqual(len(result["added"]), 1)
        self.assertEqual(result["failed"], [])
        self.assertEqual(result["added"][0]["ticker"], "ERIC-B")
        self.assertEqual(result["added"][0]["market"], "se")
        self.assertEqual(result["added"][0]["mapping_status"], "unmapped")
        self.assertEqual(result["added"][0]["cik"], "")
        self.assertEqual(companies[0]["ticker"], "ERIC-B")
        self.assertEqual(companies[0]["market"], "se")

    def test_se_ticker_variants_normalize_to_share_class_root(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            database_path = Path(temporary_directory) / "web.sqlite3"
            SQLiteInformationRepository(database_path)
            repository = WebRepository(database_path)

            result = repository.add_companies_batch(
                "ERIC-B, ERIC-B.ST, eric-b.sto",
                ("holdings",),
                None,
                market="se",
            )
            companies = repository.companies()

        self.assertEqual(len(result["added"]), 1)
        self.assertEqual(result["added"][0]["ticker"], "ERIC-B")
        self.assertEqual(len(companies), 1)

    def test_filings_status_logic_survives_se_company(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            database_path = Path(temporary_directory) / "web.sqlite3"
            SQLiteInformationRepository(database_path)
            repository = WebRepository(database_path)
            repository.add_companies_batch(
                "ERIC-B",
                ("holdings",),
                None,
                market="se",
            )

            statuses = repository.source_statuses(
                now=datetime(2026, 8, 2, 14, tzinfo=timezone.utc)
            )

        filings = next(
            record for record in statuses if record["type"] == "Filings"
        )
        self.assertEqual(filings["status"], "unavailable")


class MarketSEFinnhubSkipTests(unittest.TestCase):
    def test_finnhub_skips_se_without_http_requests(self) -> None:
        class ExplodingClient:
            def get_json(self, *args, **kwargs):
                raise AssertionError("SE must not trigger Finnhub requests")

        connector = FinnhubNewsConnector(client=ExplodingClient())

        items = connector.collect(
            CollectionRequest(
                tickers=("ERIC-B",),
                start_date=date(2026, 8, 1),
                end_date=date(2026, 8, 2),
                markets={"ERIC-B": "se"},
            )
        )

        self.assertEqual(items, [])
        self.assertEqual(connector.last_errors, ())


class MarketSEDisclosureLockTests(unittest.TestCase):
    def test_official_nasdaq_se_disclosure_is_registered(self) -> None:
        registry = create_default_registry()
        names = registry.registered_names
        self.assertIn("nasdaq_se_filings", names)
        for blocked_name in ("fi_oam", "eqs_se"):
            self.assertNotIn(blocked_name, names)

    def test_paid_nasdaq_data_products_stay_unregistered(self) -> None:
        """SE-4 regression lock: no paid Nasdaq Data Link / terminal."""
        registry = create_default_registry()

        names = registry.registered_names
        for blocked_name in ("nasdaq_datalink", "nasdaq_terminal"):
            self.assertNotIn(blocked_name, names)


if __name__ == "__main__":
    unittest.main()
