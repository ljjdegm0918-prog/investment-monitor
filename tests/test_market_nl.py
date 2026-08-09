from datetime import date, datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from investment_monitor import (
    ALLOWED_MARKETS,
    CollectionRequest,
    FinnhubNewsConnector,
    InformationItem,
    MARKET_NL,
    SQLiteInformationRepository,
    WebRepository,
)
from investment_monitor.registry import create_default_registry
from investment_monitor.web_repository import normalize_nl_ticker


class MarketNLTests(unittest.TestCase):
    def test_market_nl_is_declared(self) -> None:
        self.assertEqual(MARKET_NL, "nl")
        self.assertIn("nl", ALLOWED_MARKETS)

    def test_collection_request_accepts_nl_market(self) -> None:
        request = CollectionRequest(
            tickers=("ASML",),
            start_date=date(2026, 8, 1),
            end_date=date(2026, 8, 2),
            markets={"ASML": "nl"},
        )

        self.assertEqual(request.market_for("ASML"), "nl")

    def test_information_item_accepts_nl_market(self) -> None:
        item = InformationItem(
            source="news",
            source_type="news",
            external_id="nl-1",
            tickers=("ASML",),
            issuer="ASML",
            published_at=datetime(2026, 8, 1, tzinfo=timezone.utc),
            title="NL headline",
            document_type="news",
            url="https://example.test/nl-1",
            collected_at=datetime(2026, 8, 1, 12, tzinfo=timezone.utc),
            market="nl",
        )

        self.assertEqual(item.market, "nl")

    def test_invalid_market_is_still_rejected(self) -> None:
        with self.assertRaises(ValueError):
            CollectionRequest(
                tickers=("ASML",),
                start_date=date(2026, 8, 1),
                end_date=date(2026, 8, 2),
                markets={"ASML": "netherlands"},
            )
        with self.assertRaises(ValueError):
            InformationItem(
                source="news",
                source_type="news",
                external_id="bad",
                tickers=("ASML",),
                issuer="ASML",
                published_at=datetime(2026, 8, 1, tzinfo=timezone.utc),
                title="x",
                document_type="news",
                url="https://example.test/x",
                collected_at=datetime(2026, 8, 1, 12, tzinfo=timezone.utc),
                market="netherlands",
            )


class MarketNLTickerTests(unittest.TestCase):
    def test_normalize_nl_ticker_variants(self) -> None:
        for variant, expected in (
            ("ASML", "ASML"),
            ("ASML.AS", "ASML"),
            ("asml.as", "ASML"),
            ("ASML-AMS", "ASML"),
            ("ASML AMS", "ASML"),
            ("INGA.AS", "INGA"),
            ("ASML-AEA", "ASML"),
            ("ASML.AS.AS", "ASML"),
        ):
            self.assertEqual(normalize_nl_ticker(variant), expected)

    def test_normalize_nl_ticker_keeps_plain_input(self) -> None:
        self.assertEqual(normalize_nl_ticker("VOD"), "VOD")
        self.assertEqual(normalize_nl_ticker("abcd"), "ABCD")

    def test_normalize_nl_ticker_does_not_erase_suffix_like_codes(self) -> None:
        self.assertEqual(normalize_nl_ticker("AS"), "AS")
        self.assertEqual(normalize_nl_ticker("AMS"), "AMS")
        self.assertEqual(normalize_nl_ticker("AEA"), "AEA")
        self.assertEqual(normalize_nl_ticker("A.AS"), "A")

    def test_normalize_nl_ticker_extracts_isin(self) -> None:
        self.assertEqual(normalize_nl_ticker("NL0000235190"), "NL0000235190")
        self.assertEqual(normalize_nl_ticker("nl0000009165"), "NL0000009165")
        self.assertEqual(
            normalize_nl_ticker("ISIN: NL0000235190 "), "NL0000235190"
        )


class MarketNLWebTests(unittest.TestCase):
    def test_nl_company_is_added_as_unmapped_without_sec_resolver(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            database_path = Path(temporary_directory) / "web.sqlite3"
            SQLiteInformationRepository(database_path)
            repository = WebRepository(database_path)

            result = repository.add_companies_batch(
                "ASML.AS",
                ("holdings",),
                None,
                market="nl",
            )
            companies = repository.companies()

        self.assertEqual(len(result["added"]), 1)
        self.assertEqual(result["failed"], [])
        self.assertEqual(result["added"][0]["ticker"], "ASML")
        self.assertEqual(result["added"][0]["market"], "nl")
        self.assertEqual(result["added"][0]["mapping_status"], "unmapped")
        self.assertEqual(result["added"][0]["cik"], "")
        self.assertEqual(companies[0]["ticker"], "ASML")
        self.assertEqual(companies[0]["market"], "nl")

    def test_nl_ticker_variants_normalize_to_root(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            database_path = Path(temporary_directory) / "web.sqlite3"
            SQLiteInformationRepository(database_path)
            repository = WebRepository(database_path)

            result = repository.add_companies_batch(
                "ASML, ASML.AS, asml-AMS",
                ("holdings",),
                None,
                market="nl",
            )
            companies = repository.companies()

        self.assertEqual(len(result["added"]), 1)
        self.assertEqual(result["added"][0]["ticker"], "ASML")
        self.assertEqual(len(companies), 1)

    def test_filings_status_logic_survives_nl_company(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            database_path = Path(temporary_directory) / "web.sqlite3"
            SQLiteInformationRepository(database_path)
            repository = WebRepository(database_path)
            repository.add_companies_batch(
                "ASML",
                ("holdings",),
                None,
                market="nl",
            )

            statuses = repository.source_statuses(
                now=datetime(2026, 8, 2, 14, tzinfo=timezone.utc)
            )

        filings = next(
            record for record in statuses if record["type"] == "Filings"
        )
        self.assertEqual(filings["status"], "unavailable")


class MarketNLFinnhubSkipTests(unittest.TestCase):
    def test_finnhub_skips_nl_without_http_requests(self) -> None:
        class ExplodingClient:
            def get_json(self, *args, **kwargs):
                raise AssertionError("NL must not trigger Finnhub requests")

        connector = FinnhubNewsConnector(client=ExplodingClient())

        items = connector.collect(
            CollectionRequest(
                tickers=("ASML",),
                start_date=date(2026, 8, 1),
                end_date=date(2026, 8, 2),
                markets={"ASML": "nl"},
            )
        )

        self.assertEqual(items, [])
        self.assertEqual(connector.last_errors, ())


class MarketNLDisclosureFollowupTests(unittest.TestCase):
    def test_eqs_nl_remains_registered(self) -> None:
        registry = create_default_registry()

        self.assertIsNotNone(registry.factory_for("eqs_nl"))

    def test_no_second_nl_disclosure_connector_is_registered(self) -> None:
        """Lock the NL-4 D2 spike decision.

        NL-4 re-verified (2026-08-10): AFM registers are HTML-only with no
        stable key-free JSON, Euronext announcement pages are Drupal
        antibot HTML and the guessed JSON endpoint 404s, and Euronext web
        services are paid. EQS News (NL) by Dutch ISIN stays the only wired
        NL disclosure source. Remove this test when a real second source
        lands.
        """
        registry = create_default_registry()

        names = registry.registered_names
        for blocked_name in (
            "afm_nl",
            "euronext_nl_announcements",
            "eqs_nl_alt",
        ):
            self.assertNotIn(blocked_name, names)


if __name__ == "__main__":
    unittest.main()
