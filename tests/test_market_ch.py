from datetime import date, datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from investment_monitor import (
    ALLOWED_MARKETS,
    CollectionRequest,
    FinnhubNewsConnector,
    InformationItem,
    MARKET_CH,
    SQLiteInformationRepository,
    WebRepository,
)
from investment_monitor.registry import create_default_registry
from investment_monitor.web_repository import normalize_ch_ticker


class MarketCHTests(unittest.TestCase):
    def test_market_ch_is_declared(self) -> None:
        self.assertEqual(MARKET_CH, "ch")
        self.assertIn("ch", ALLOWED_MARKETS)

    def test_collection_request_accepts_ch_market(self) -> None:
        request = CollectionRequest(
            tickers=("NESN",),
            start_date=date(2026, 8, 1),
            end_date=date(2026, 8, 2),
            markets={"NESN": "ch"},
        )

        self.assertEqual(request.market_for("NESN"), "ch")

    def test_information_item_accepts_ch_market(self) -> None:
        item = InformationItem(
            source="news",
            source_type="news",
            external_id="ch-1",
            tickers=("NESN",),
            issuer="NESN",
            published_at=datetime(2026, 8, 1, tzinfo=timezone.utc),
            title="CH headline",
            document_type="news",
            url="https://example.test/ch-1",
            collected_at=datetime(2026, 8, 1, 12, tzinfo=timezone.utc),
            market="ch",
        )

        self.assertEqual(item.market, "ch")

    def test_invalid_market_is_still_rejected(self) -> None:
        with self.assertRaises(ValueError):
            CollectionRequest(
                tickers=("NESN",),
                start_date=date(2026, 8, 1),
                end_date=date(2026, 8, 2),
                markets={"NESN": "swiss"},
            )
        with self.assertRaises(ValueError):
            InformationItem(
                source="news",
                source_type="news",
                external_id="bad",
                tickers=("NESN",),
                issuer="NESN",
                published_at=datetime(2026, 8, 1, tzinfo=timezone.utc),
                title="x",
                document_type="news",
                url="https://example.test/x",
                collected_at=datetime(2026, 8, 1, 12, tzinfo=timezone.utc),
                market="swiss",
            )


class MarketCHTickerTests(unittest.TestCase):
    def test_normalize_ch_ticker_variants(self) -> None:
        for variant, expected in (
            ("NESN", "NESN"),
            ("NESN.SW", "NESN"),
            ("nesn.sw", "NESN"),
            ("NESN-SWX", "NESN"),
            ("NESN SW", "NESN"),
            ("ROG.SW", "ROG"),
            ("UBSG.SW", "UBSG"),
            ("ABBN.S", "ABBN"),
            ("NESN.SW.SW", "NESN"),
        ):
            self.assertEqual(normalize_ch_ticker(variant), expected)

    def test_normalize_ch_ticker_keeps_plain_input(self) -> None:
        self.assertEqual(normalize_ch_ticker("VOD"), "VOD")
        self.assertEqual(normalize_ch_ticker("abcd"), "ABCD")

    def test_normalize_ch_ticker_does_not_erase_suffix_like_codes(self) -> None:
        self.assertEqual(normalize_ch_ticker("SW"), "SW")
        self.assertEqual(normalize_ch_ticker("SWX"), "SWX")
        self.assertEqual(normalize_ch_ticker("S"), "S")
        self.assertEqual(normalize_ch_ticker("A.SW"), "A")

    def test_normalize_ch_ticker_extracts_isin(self) -> None:
        self.assertEqual(normalize_ch_ticker("CH0038863350"), "CH0038863350")
        self.assertEqual(normalize_ch_ticker("ch0038863350"), "CH0038863350")
        self.assertEqual(
            normalize_ch_ticker("ISIN: CH0038863350 "), "CH0038863350"
        )


class MarketCHWebTests(unittest.TestCase):
    def test_ch_company_is_added_as_unmapped_without_sec_resolver(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            database_path = Path(temporary_directory) / "web.sqlite3"
            SQLiteInformationRepository(database_path)
            repository = WebRepository(database_path)

            result = repository.add_companies_batch(
                "NESN.SW",
                ("holdings",),
                None,
                market="ch",
            )
            companies = repository.companies()

        self.assertEqual(len(result["added"]), 1)
        self.assertEqual(result["failed"], [])
        self.assertEqual(result["added"][0]["ticker"], "NESN")
        self.assertEqual(result["added"][0]["market"], "ch")
        self.assertEqual(result["added"][0]["mapping_status"], "unmapped")
        self.assertEqual(result["added"][0]["cik"], "")
        self.assertEqual(companies[0]["ticker"], "NESN")
        self.assertEqual(companies[0]["market"], "ch")

    def test_ch_ticker_variants_normalize_to_root(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            database_path = Path(temporary_directory) / "web.sqlite3"
            SQLiteInformationRepository(database_path)
            repository = WebRepository(database_path)

            result = repository.add_companies_batch(
                "NESN, NESN.SW, nesn-SWX",
                ("holdings",),
                None,
                market="ch",
            )
            companies = repository.companies()

        self.assertEqual(len(result["added"]), 1)
        self.assertEqual(result["added"][0]["ticker"], "NESN")
        self.assertEqual(len(companies), 1)

    def test_filings_status_logic_survives_ch_company(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            database_path = Path(temporary_directory) / "web.sqlite3"
            SQLiteInformationRepository(database_path)
            repository = WebRepository(database_path)
            repository.add_companies_batch(
                "NESN",
                ("holdings",),
                None,
                market="ch",
            )

            statuses = repository.source_statuses(
                now=datetime(2026, 8, 2, 14, tzinfo=timezone.utc)
            )

        filings = next(
            record for record in statuses if record["type"] == "Filings"
        )
        self.assertEqual(filings["status"], "unavailable")


class MarketCHFinnhubSkipTests(unittest.TestCase):
    def test_finnhub_skips_ch_without_http_requests(self) -> None:
        class ExplodingClient:
            def get_json(self, *args, **kwargs):
                raise AssertionError("CH must not trigger Finnhub requests")

        connector = FinnhubNewsConnector(client=ExplodingClient())

        items = connector.collect(
            CollectionRequest(
                tickers=("NESN",),
                start_date=date(2026, 8, 1),
                end_date=date(2026, 8, 2),
                markets={"NESN": "ch"},
            )
        )

        self.assertEqual(items, [])
        self.assertEqual(connector.last_errors, ())


class MarketCHDisclosureFollowupTests(unittest.TestCase):
    def test_eqs_ch_remains_registered(self) -> None:
        registry = create_default_registry()

        self.assertIsNotNone(registry.factory_for("eqs_ch"))

    def test_no_second_ch_disclosure_connector_is_registered(self) -> None:
        """Lock the CH-4 second-source boundary.

        CH-4 re-verified (2026-08-10): SIX official notices are served by a
        React SPA with no public JSON list; ``api.six-group.com`` /
        ``webapp.api.six-group.com`` routes are undocumented 404s; SIX
        equity-issuer news is the paid Exfeed product; FINMA has no
        per-issuer announcement feed. EQS News (CH) by Swiss ISIN stays the
        only wired CH disclosure source. Remove entries from the blocked
        list only when a real key-free source lands.
        """
        registry = create_default_registry()

        names = registry.registered_names
        for blocked_name in (
            "six_official_notices",
            "six_datalink",
            "exfeed",
            "eqs_ch_alt",
        ):
            self.assertNotIn(blocked_name, names)


if __name__ == "__main__":
    unittest.main()
