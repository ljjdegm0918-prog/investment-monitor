from datetime import date, datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from investment_monitor import (
    ALLOWED_MARKETS,
    CollectionRequest,
    FinnhubNewsConnector,
    InformationItem,
    MARKET_EMF,
    SQLiteInformationRepository,
    WebRepository,
)
from investment_monitor.registry import create_default_registry
from investment_monitor.web_repository import normalize_emf_ticker


class MarketEMFTests(unittest.TestCase):
    def test_market_emf_is_declared(self) -> None:
        self.assertEqual(MARKET_EMF, "emf")
        self.assertIn("emf", ALLOWED_MARKETS)

    def test_no_over_broad_fund_market_codes(self) -> None:
        """EMF-0 lock: the fund track must not use an over-broad code."""
        for blocked in ("fund", "funds", "mf", "ucits"):
            self.assertNotIn(blocked, ALLOWED_MARKETS)

    def test_collection_request_accepts_emf_market(self) -> None:
        request = CollectionRequest(
            tickers=("LU0171254561",),
            start_date=date(2026, 8, 1),
            end_date=date(2026, 8, 2),
            markets={"LU0171254561": "emf"},
        )

        self.assertEqual(request.market_for("LU0171254561"), "emf")

    def test_information_item_accepts_emf_market(self) -> None:
        item = InformationItem(
            source="news",
            source_type="news",
            external_id="emf-1",
            tickers=("LU0171254561",),
            issuer="BlackRock Global Allocation Fund",
            published_at=datetime(2026, 8, 1, tzinfo=timezone.utc),
            title="EMF headline",
            document_type="news",
            url="https://example.test/emf-1",
            collected_at=datetime(2026, 8, 1, 12, tzinfo=timezone.utc),
            market="emf",
        )

        self.assertEqual(item.market, "emf")

    def test_invalid_market_is_still_rejected(self) -> None:
        with self.assertRaises(ValueError):
            CollectionRequest(
                tickers=("LU0171254561",),
                start_date=date(2026, 8, 1),
                end_date=date(2026, 8, 2),
                markets={"LU0171254561": "funds"},
            )


class MarketEMFTickerTests(unittest.TestCase):
    def test_normalize_emf_ticker_extracts_isin_first(self) -> None:
        for variant, expected in (
            ("LU0171254561", "LU0171254561"),
            ("lu0171254561", "LU0171254561"),
            ("ISIN: LU0171254561", "LU0171254561"),
            ("LU0171254561.F", "LU0171254561"),
            ("LU0171254561 MF", "LU0171254561"),
            ("LU0171254561-MF.F", "LU0171254561"),
            ("GB00B1XZS820", "GB00B1XZS820"),
            ("IE00B4L5Y983", "IE00B4L5Y983"),
        ):
            self.assertEqual(normalize_emf_ticker(variant), expected)

    def test_normalize_emf_ticker_keeps_plain_input(self) -> None:
        self.assertEqual(normalize_emf_ticker("BLACKROCK"), "BLACKROCK")
        self.assertEqual(normalize_emf_ticker("abcd"), "ABCD")

    def test_normalize_emf_ticker_does_not_erase_suffix_like_codes(self) -> None:
        self.assertEqual(normalize_emf_ticker("F"), "F")
        self.assertEqual(normalize_emf_ticker("MF"), "MF")


class MarketEMFWebTests(unittest.TestCase):
    def test_emf_fund_is_added_as_unmapped_without_sec_resolver(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            database_path = Path(temporary_directory) / "web.sqlite3"
            SQLiteInformationRepository(database_path)
            repository = WebRepository(database_path)

            result = repository.add_companies_batch(
                "LU0171254561.F",
                ("holdings",),
                None,
                market="emf",
            )
            companies = repository.companies()

        self.assertEqual(len(result["added"]), 1)
        self.assertEqual(result["failed"], [])
        self.assertEqual(result["added"][0]["ticker"], "LU0171254561")
        self.assertEqual(result["added"][0]["market"], "emf")
        self.assertEqual(result["added"][0]["mapping_status"], "unmapped")
        self.assertEqual(result["added"][0]["cik"], "")
        self.assertEqual(companies[0]["ticker"], "LU0171254561")
        self.assertEqual(companies[0]["market"], "emf")

    def test_emf_isin_variants_normalize_to_root(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            database_path = Path(temporary_directory) / "web.sqlite3"
            SQLiteInformationRepository(database_path)
            repository = WebRepository(database_path)

            result = repository.add_companies_batch(
                "LU0171254561, lu0171254561.F, LU0171254561-MF",
                ("holdings",),
                None,
                market="emf",
            )
            companies = repository.companies()

        self.assertEqual(len(result["added"]), 1)
        self.assertEqual(result["added"][0]["ticker"], "LU0171254561")
        self.assertEqual(len(companies), 1)

    def test_filings_status_logic_survives_emf_fund(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            database_path = Path(temporary_directory) / "web.sqlite3"
            SQLiteInformationRepository(database_path)
            repository = WebRepository(database_path)
            repository.add_companies_batch(
                "LU0171254561",
                ("holdings",),
                None,
                market="emf",
            )

            statuses = repository.source_statuses(
                now=datetime(2026, 8, 2, 14, tzinfo=timezone.utc)
            )

        filings = next(
            record for record in statuses if record["type"] == "Filings"
        )
        self.assertEqual(filings["status"], "unavailable")


class MarketEMFFinnhubSkipTests(unittest.TestCase):
    def test_finnhub_skips_emf_without_http_requests(self) -> None:
        class ExplodingClient:
            def get_json(self, *args, **kwargs):
                raise AssertionError("EMF must not trigger Finnhub requests")

        connector = FinnhubNewsConnector(client=ExplodingClient())

        items = connector.collect(
            CollectionRequest(
                tickers=("LU0171254561",),
                start_date=date(2026, 8, 1),
                end_date=date(2026, 8, 2),
                markets={"LU0171254561": "emf"},
            )
        )

        self.assertEqual(items, [])
        self.assertEqual(connector.last_errors, ())


class MarketEMFDisclosureLockTests(unittest.TestCase):
    def test_no_emf_disclosure_connector_is_registered_yet(self) -> None:
        """Lock the EMF-1 spike decision until a key-free source lands.

        EMF-1 spike (2026-08-10): the ESMA registers expose a funds core
        (AIFMD: AIF/EuVECA/ELTIF/EuSEF, ~107k reports) and a MiFID firms
        core, but no UCITS register and no ISIN field is exposed via the
        public SOLR surface; KIID/PRIIPs documents live on manager sites
        with no central key-free feed. No fund disclosure connector is
        wired and no stock OAM is re-mapped onto market=emf. Remove this
        test when a real key-free European fund disclosure source lands.
        """
        registry = create_default_registry()

        names = registry.registered_names
        for blocked_name in (
            "emf_disclosure",
            "esma_fund_disclosure",
            "kiid_fund_filings",
            "emf_second_disclosure",
            "morningstar_paid",
            "lipper_paid",
            "eurex_funds",
        ):
            self.assertNotIn(blocked_name, names)


if __name__ == "__main__":
    unittest.main()
