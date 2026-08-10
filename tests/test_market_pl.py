from datetime import date, datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from investment_monitor import (
    ALLOWED_MARKETS,
    CollectionRequest,
    FinnhubNewsConnector,
    InformationItem,
    MARKET_PL,
    SQLiteInformationRepository,
    WebRepository,
)
from investment_monitor.registry import create_default_registry
from investment_monitor.web_repository import normalize_pl_ticker


class MarketPLTests(unittest.TestCase):
    def test_market_pl_is_declared(self) -> None:
        self.assertEqual(MARKET_PL, "pl")
        self.assertIn("pl", ALLOWED_MARKETS)

    def test_collection_request_accepts_pl_market(self) -> None:
        request = CollectionRequest(
            tickers=("PKO",),
            start_date=date(2026, 8, 1),
            end_date=date(2026, 8, 2),
            markets={"PKO": "pl"},
        )

        self.assertEqual(request.market_for("PKO"), "pl")

    def test_information_item_accepts_pl_market(self) -> None:
        item = InformationItem(
            source="news",
            source_type="news",
            external_id="pl-1",
            tickers=("PKO",),
            issuer="PKO",
            published_at=datetime(2026, 8, 1, tzinfo=timezone.utc),
            title="PL headline",
            document_type="news",
            url="https://example.test/pl-1",
            collected_at=datetime(2026, 8, 1, 12, tzinfo=timezone.utc),
            market="pl",
        )

        self.assertEqual(item.market, "pl")

    def test_invalid_market_is_still_rejected(self) -> None:
        with self.assertRaises(ValueError):
            CollectionRequest(
                tickers=("PKO",),
                start_date=date(2026, 8, 1),
                end_date=date(2026, 8, 2),
                markets={"PKO": "poland"},
            )
        with self.assertRaises(ValueError):
            InformationItem(
                source="news",
                source_type="news",
                external_id="bad",
                tickers=("PKO",),
                issuer="PKO",
                published_at=datetime(2026, 8, 1, tzinfo=timezone.utc),
                title="x",
                document_type="news",
                url="https://example.test/x",
                collected_at=datetime(2026, 8, 1, 12, tzinfo=timezone.utc),
                market="poland",
            )


class MarketPLTickerTests(unittest.TestCase):
    def test_normalize_pl_ticker_variants(self) -> None:
        for variant, expected in (
            ("PKO", "PKO"),
            ("PKO.WA", "PKO"),
            ("pko.wa", "PKO"),
            ("PKO-WSE", "PKO"),
            ("PKO GPW", "PKO"),
            ("PKN.WA", "PKN"),
            ("PZU.WA", "PZU"),
            ("CDR.WA", "CDR"),
            ("PKO.WA.WA", "PKO"),
        ):
            self.assertEqual(normalize_pl_ticker(variant), expected)

    def test_normalize_pl_ticker_keeps_plain_input(self) -> None:
        self.assertEqual(normalize_pl_ticker("VOD"), "VOD")
        self.assertEqual(normalize_pl_ticker("abcd"), "ABCD")

    def test_normalize_pl_ticker_does_not_erase_suffix_like_codes(self) -> None:
        self.assertEqual(normalize_pl_ticker("WA"), "WA")
        self.assertEqual(normalize_pl_ticker("WSE"), "WSE")
        self.assertEqual(normalize_pl_ticker("GPW"), "GPW")
        self.assertEqual(normalize_pl_ticker("A.WA"), "A")

    def test_normalize_pl_ticker_extracts_isin(self) -> None:
        self.assertEqual(normalize_pl_ticker("PLPKO0000016"), "PLPKO0000016")
        self.assertEqual(normalize_pl_ticker("plPKO0000016"), "PLPKO0000016")
        self.assertEqual(
            normalize_pl_ticker("ISIN: PLPKO0000016 "), "PLPKO0000016"
        )


class MarketPLWebTests(unittest.TestCase):
    def test_pl_company_is_added_as_unmapped_without_sec_resolver(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            database_path = Path(temporary_directory) / "web.sqlite3"
            SQLiteInformationRepository(database_path)
            repository = WebRepository(database_path)

            result = repository.add_companies_batch(
                "PKO.WA",
                ("holdings",),
                None,
                market="pl",
            )
            companies = repository.companies()

        self.assertEqual(len(result["added"]), 1)
        self.assertEqual(result["failed"], [])
        self.assertEqual(result["added"][0]["ticker"], "PKO")
        self.assertEqual(result["added"][0]["market"], "pl")
        self.assertEqual(result["added"][0]["mapping_status"], "unmapped")
        self.assertEqual(result["added"][0]["cik"], "")
        self.assertEqual(companies[0]["ticker"], "PKO")
        self.assertEqual(companies[0]["market"], "pl")

    def test_pl_ticker_variants_normalize_to_root(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            database_path = Path(temporary_directory) / "web.sqlite3"
            SQLiteInformationRepository(database_path)
            repository = WebRepository(database_path)

            result = repository.add_companies_batch(
                "PKO, PKO.WA, pko-GPW",
                ("holdings",),
                None,
                market="pl",
            )
            companies = repository.companies()

        self.assertEqual(len(result["added"]), 1)
        self.assertEqual(result["added"][0]["ticker"], "PKO")
        self.assertEqual(len(companies), 1)

    def test_filings_status_logic_survives_pl_company(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            database_path = Path(temporary_directory) / "web.sqlite3"
            SQLiteInformationRepository(database_path)
            repository = WebRepository(database_path)
            repository.add_companies_batch(
                "PKO",
                ("holdings",),
                None,
                market="pl",
            )

            statuses = repository.source_statuses(
                now=datetime(2026, 8, 2, 14, tzinfo=timezone.utc)
            )

        filings = next(
            record for record in statuses if record["type"] == "Filings"
        )
        self.assertEqual(filings["status"], "unavailable")


class MarketPLFinnhubSkipTests(unittest.TestCase):
    def test_finnhub_skips_pl_without_http_requests(self) -> None:
        class ExplodingClient:
            def get_json(self, *args, **kwargs):
                raise AssertionError("PL must not trigger Finnhub requests")

        connector = FinnhubNewsConnector(client=ExplodingClient())

        items = connector.collect(
            CollectionRequest(
                tickers=("PKO",),
                start_date=date(2026, 8, 1),
                end_date=date(2026, 8, 2),
                markets={"PKO": "pl"},
            )
        )

        self.assertEqual(items, [])
        self.assertEqual(connector.last_errors, ())


class MarketPLDisclosureLockTests(unittest.TestCase):
    def test_gpw_espi_is_registered(self) -> None:
        """PL-4 re-spike (2026-08-10) found the official GPW reports page.

        ``www.gpw.pl/komunikaty`` is a key-free server-rendered ESPI/EBI
        list filterable by Polish ISIN, so the PL-1 A3 boundary (which was
        based on ``espi.gpw.pl`` TLS failure and empty EQS records) no
        longer applies to this page. ``gpw_espi`` is the wired connector.
        """
        registry = create_default_registry()

        self.assertIsNotNone(registry.factory_for("gpw_espi"))
        self.assertEqual(registry.secret_fields_for("gpw_espi"), ())

    def test_unwired_pl_disclosure_names_stay_unregistered(self) -> None:
        """Lock the paid/unavailable PL disclosure boundaries."""
        registry = create_default_registry()

        names = registry.registered_names
        for blocked_name in (
            "espi_pl",
            "eqs_pl",
            "knf_filings",
            "gpw_datalink",
        ):
            self.assertNotIn(blocked_name, names)


if __name__ == "__main__":
    unittest.main()
