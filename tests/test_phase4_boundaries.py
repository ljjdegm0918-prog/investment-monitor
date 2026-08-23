"""Phase 4 boundary tests: CA/SG/SE/CH main-chain and ETF honesty."""

import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from investment_monitor.ca_universe import PHASE4_BOUNDARY as CA_BOUNDARY
from investment_monitor.universe.sg_universe import PHASE4_BOUNDARY as SG_BOUNDARY
from investment_monitor.universe.se_universe import PHASE4_BOUNDARY as SE_BOUNDARY
from investment_monitor.universe.ch_universe import PHASE4_BOUNDARY as CH_BOUNDARY
from investment_monitor.universe.coverage_report import coverage_report
from investment_monitor.universe.exchange_catalog import list_countries
from investment_monitor.registry import SOURCE_MARKETS


class Phase4BoundaryTests(unittest.TestCase):
    def test_ca_boundary_is_locked_partial(self):
        self.assertEqual(CA_BOUNDARY["universe"], "partial")
        self.assertEqual(CA_BOUNDARY["disclosure"], "partial")
        self.assertIn("SEDAR+", CA_BOUNDARY["evidence"])

    def test_sg_boundary_is_locked_partial(self):
        self.assertEqual(SG_BOUNDARY["universe"], "partial")
        self.assertEqual(SG_BOUNDARY["disclosure"], "partial")
        self.assertIn("api.sgx.com", SG_BOUNDARY["evidence"])

    def test_se_boundary_keeps_live_filings_and_partial_official_universe(self):
        self.assertEqual(SE_BOUNDARY["universe"], "partial")
        self.assertEqual(SE_BOUNDARY["disclosure"], "live")
        self.assertIn("nordic/screener/shares", SE_BOUNDARY["evidence"])

    def test_ch_boundary_keeps_partial_disclosure(self):
        self.assertEqual(CH_BOUNDARY["universe"], "stub")
        self.assertEqual(CH_BOUNDARY["disclosure"], "partial")
        self.assertIn("404", CH_BOUNDARY["evidence"])


class Phase4CoverageTests(unittest.TestCase):
    def setUp(self):
        self.report = coverage_report()
        self.rows = {
            row["country_code"]: row for row in self.report["countries"]
        }

    def test_coverage_matches_phase4_boundaries(self):
        self.assertEqual(self.rows["CA"]["universe"], CA_BOUNDARY["universe"])
        self.assertEqual(self.rows["CA"]["disclosure"], CA_BOUNDARY["disclosure"])
        self.assertEqual(self.rows["SG"]["universe"], SG_BOUNDARY["universe"])
        self.assertEqual(self.rows["SG"]["disclosure"], SG_BOUNDARY["disclosure"])
        self.assertEqual(self.rows["SE"]["universe"], SE_BOUNDARY["universe"])
        self.assertEqual(self.rows["SE"]["disclosure"], SE_BOUNDARY["disclosure"])
        self.assertEqual(self.rows["CH"]["universe"], CH_BOUNDARY["universe"])
        self.assertEqual(self.rows["CH"]["disclosure"], CH_BOUNDARY["disclosure"])

    def test_phase4_notes_expose_locked_boundaries(self):
        for code in ("CA", "SG", "SE", "CH"):
            self.assertIn("boundary", self.rows[code]["notes"], code)

    def test_de_golden_etf_stays_live(self):
        self.assertEqual(self.rows["DE"]["etf_universe"], "live")
        self.assertEqual(self.rows["DE"]["universe"], "live")

    def test_etf_candidates_flip_uncovered_markets_to_partial(self):
        with TemporaryDirectory() as tmp:
            cache = Path(tmp) / "global.json"
            items = []
            for market in ("uk", "hk", "jp", "tw", "au", "pl", "es"):
                items.append({
                    "market": market, "symbol": f"ETF{market.upper()}",
                    "instrument_type": "etf", "name": "ETF candidate",
                })
            cache.write_text(json.dumps({"items": items}), encoding="utf-8")
            report = coverage_report(cache_path=cache)
            rows = {
                row["country_code"]: row for row in report["countries"]
            }
            for code, market in (
                ("GB", "uk"), ("HK", "hk"), ("TW", "tw"),
                ("AU", "au"), ("PL", "pl"), ("ES", "es"),
            ):
                self.assertEqual(
                    rows[code]["etf_universe"], "partial", code
                )
            self.assertEqual(rows["JP"]["etf_universe"], "live")


class Phase4VenueAndUkEtfTests(unittest.TestCase):
    def test_cxe_trq_have_no_disclosure_connectors(self):
        for market in ("cxe", "trq"):
            scoped = {
                name for name, scope in SOURCE_MARKETS.items()
                if scope == market
            }
            self.assertTrue(scoped <= {"google_news_cxe", "google_news_trq"})
            for name in scoped:
                self.assertIn("news", name, market)
        extras = {
            row["country_code"]: row
            for row in list_countries(include_extra=True)
        }
        self.assertEqual(extras["CXE"]["catalog_role"], "venue_only")
        self.assertEqual(extras["TRQ"]["catalog_role"], "venue_only")

    def test_uk_firds_etf_rows_raise_etf_to_partial(self):
        saved = os.environ.get("UK_UNIVERSE_CACHE_PATH")
        with TemporaryDirectory() as tmp:
            cache = Path(tmp) / "uk.json"
            cache.write_text(json.dumps({
                "source": "firds",
                "items": [
                    {"ticker": "VOD", "name": "VODAFONE",
                     "isin": "GB00BH4HKS39", "instrument_kind": "equity"},
                    {"ticker": "", "name": "ISHARES CORE FTSE 100",
                     "isin": "IE0005042456", "instrument_kind": "etf"},
                ],
            }), encoding="utf-8")
            os.environ["UK_UNIVERSE_CACHE_PATH"] = str(cache)
            try:
                report = coverage_report()
                rows = {
                    row["country_code"]: row
                    for row in report["countries"]
                }
                self.assertEqual(rows["GB"]["etf_universe"], "partial")
            finally:
                if saved is None:
                    os.environ.pop("UK_UNIVERSE_CACHE_PATH", None)
                else:
                    os.environ["UK_UNIVERSE_CACHE_PATH"] = saved


if __name__ == "__main__":
    unittest.main()
