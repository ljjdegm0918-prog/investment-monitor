from datetime import date, datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from investment_monitor import (
    ALLOWED_MARKETS,
    CollectionRequest,
    InformationItem,
    MARKET_FR,
    SQLiteInformationRepository,
    WebRepository,
)
from investment_monitor.web_repository import normalize_fr_ticker


class MarketFRTests(unittest.TestCase):
    def test_market_fr_is_declared(self) -> None:
        self.assertEqual(MARKET_FR, "fr")
        self.assertIn("fr", ALLOWED_MARKETS)

    def test_collection_request_accepts_fr_market(self) -> None:
        request = CollectionRequest(
            tickers=("MC",),
            start_date=date(2026, 8, 1),
            end_date=date(2026, 8, 2),
            markets={"MC": "fr"},
        )

        self.assertEqual(request.market_for("MC"), "fr")

    def test_information_item_accepts_fr_market(self) -> None:
        item = InformationItem(
            source="news",
            source_type="news",
            external_id="fr-1",
            tickers=("MC",),
            issuer="MC",
            published_at=datetime(2026, 8, 1, tzinfo=timezone.utc),
            title="FR headline",
            document_type="news",
            url="https://example.test/fr-1",
            collected_at=datetime(2026, 8, 1, 12, tzinfo=timezone.utc),
            market="fr",
        )

        self.assertEqual(item.market, "fr")

    def test_invalid_market_is_still_rejected(self) -> None:
        with self.assertRaises(ValueError):
            CollectionRequest(
                tickers=("MC",),
                start_date=date(2026, 8, 1),
                end_date=date(2026, 8, 2),
                markets={"MC": "france"},
            )
        with self.assertRaises(ValueError):
            InformationItem(
                source="news",
                source_type="news",
                external_id="bad",
                tickers=("MC",),
                issuer="MC",
                published_at=datetime(2026, 8, 1, tzinfo=timezone.utc),
                title="x",
                document_type="news",
                url="https://example.test/x",
                collected_at=datetime(2026, 8, 1, 12, tzinfo=timezone.utc),
                market="france",
            )


class MarketFRTickerTests(unittest.TestCase):
    def test_normalize_fr_ticker_variants(self) -> None:
        for variant, expected in (
            ("MC", "MC"),
            ("MC.PA", "MC"),
            ("mc.pa", "MC"),
            ("MC-PAR", "MC"),
            ("MC PA", "MC"),
            ("TTE.PA", "TTE"),
            ("MC.PA.PA", "MC"),
        ):
            self.assertEqual(normalize_fr_ticker(variant), expected)

    def test_normalize_fr_ticker_keeps_plain_input(self) -> None:
        self.assertEqual(normalize_fr_ticker("VOD"), "VOD")
        self.assertEqual(normalize_fr_ticker("abcd"), "ABCD")

    def test_normalize_fr_ticker_does_not_erase_suffix_like_codes(self) -> None:
        self.assertEqual(normalize_fr_ticker("PA"), "PA")
        self.assertEqual(normalize_fr_ticker("PAR"), "PAR")
        self.assertEqual(normalize_fr_ticker("A.PA"), "A")

    def test_normalize_fr_ticker_extracts_isin(self) -> None:
        self.assertEqual(normalize_fr_ticker("FR0000120271"), "FR0000120271")
        self.assertEqual(normalize_fr_ticker("fr0000120073"), "FR0000120073")
        self.assertEqual(
            normalize_fr_ticker("ISIN: FR0000121014 "), "FR0000121014"
        )


class MarketFRWebTests(unittest.TestCase):
    def test_fr_company_is_added_as_unmapped_without_sec_resolver(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            database_path = Path(temporary_directory) / "web.sqlite3"
            SQLiteInformationRepository(database_path)
            repository = WebRepository(database_path)

            result = repository.add_companies_batch(
                "MC.PA",
                ("holdings",),
                None,
                market="fr",
            )
            companies = repository.companies()

        self.assertEqual(len(result["added"]), 1)
        self.assertEqual(result["failed"], [])
        self.assertEqual(result["added"][0]["ticker"], "MC")
        self.assertEqual(result["added"][0]["market"], "fr")
        self.assertEqual(result["added"][0]["mapping_status"], "unmapped")
        self.assertEqual(result["added"][0]["cik"], "")
        self.assertEqual(companies[0]["ticker"], "MC")
        self.assertEqual(companies[0]["market"], "fr")

    def test_fr_ticker_variants_normalize_to_root(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            database_path = Path(temporary_directory) / "web.sqlite3"
            SQLiteInformationRepository(database_path)
            repository = WebRepository(database_path)

            result = repository.add_companies_batch(
                "MC, MC.PA, mc-PAR",
                ("holdings",),
                None,
                market="fr",
            )
            companies = repository.companies()

        self.assertEqual(len(result["added"]), 1)
        self.assertEqual(result["added"][0]["ticker"], "MC")
        self.assertEqual(len(companies), 1)


if __name__ == "__main__":
    unittest.main()
