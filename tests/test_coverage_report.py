"""P0-1 coverage report tests."""

import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from investment_monitor.universe.coverage_report import coverage_report


class CoverageReportTests(unittest.TestCase):
    def setUp(self):
        self.report = coverage_report()
        self.rows = {row["country_code"]: row for row in self.report["countries"]}

    def test_report_covers_28_countries_and_87_venues(self):
        self.assertEqual(self.report["schema"], "coverage_report/v2")
        self.assertEqual(
            self.report["scope"],
            {
                "kind": "independent_market_information_coverage",
                "broker_runtime_dependency": False,
                "broker_account_required": False,
                "trading_capability_assessed": False,
            },
        )
        self.assertEqual(self.report["summary"]["countries"], 28)
        self.assertEqual(self.report["summary"]["venues"], 87)
        self.assertEqual(len(self.rows), 28)

    def test_sample_country_statuses(self):
        de = self.rows["DE"]
        self.assertEqual(de["universe"], "live")
        self.assertEqual(de["disclosure"], "partial")
        self.assertEqual(de["etf_universe"], "live")
        self.assertEqual(de["source_tier_summary"], "mixed")

        in_row = self.rows["IN"]
        self.assertEqual(in_row["universe"], "live")
        self.assertEqual(in_row["disclosure"], "live")

        gb = self.rows["GB"]
        self.assertEqual(gb["disclosure"], "live")

        at = self.rows["AT"]
        self.assertEqual(at["universe"], "live")
        self.assertEqual(at["disclosure"], "partial")

        ru = self.rows["RU"]
        self.assertNotIn("trading_status", ru)
        self.assertEqual(ru["universe"], "partial")
        self.assertEqual(ru["disclosure"], "unavailable")
        self.assertEqual(ru["news"], "unavailable")
        self.assertEqual(ru["source_tier_summary"], "mixed")
        self.assertIn("research-only", ru["notes"])

    def test_boundary_stubs_are_never_live(self):
        for code in ("CH", "HU", "IL", "MX", "SE", "SG"):
            self.assertNotEqual(self.rows[code]["universe"], "live", code)

    def test_all_disclosure_statuses_use_the_canonical_market_key(self):
        expected = {
            "CA": "partial", "MX": "live", "US": "live",
            "AT": "partial", "BE": "live", "CH": "partial",
            "DE": "partial", "EE": "live", "ES": "live",
            "FR": "live", "GB": "live", "HU": "partial",
            "IL": "live", "IT": "partial", "LT": "live",
            "LV": "live", "NL": "partial", "NO": "live",
            "PL": "live", "PT": "live", "RU": "unavailable",
            "SE": "live", "AU": "live", "HK": "live",
            "IN": "live", "JP": "live", "SG": "partial",
            "TW": "live",
        }
        self.assertEqual(
            {code: row["disclosure"] for code, row in self.rows.items()},
            expected,
        )

    def test_etf_candidates_flip_partial(self):
        with TemporaryDirectory() as tmp:
            cache = Path(tmp) / "global.json"
            cache.write_text(json.dumps({
                "items": [{
                    "market": "be", "symbol": "EUNL",
                    "instrument_type": "etf", "name": "EUNL",
                }]
            }), encoding="utf-8")
            report = coverage_report(cache_path=cache)
            rows = {row["country_code"]: row for row in report["countries"]}
            self.assertEqual(rows["BE"]["etf_universe"], "partial")

    def test_news_available_everywhere_except_ru(self):
        live_news = sum(
            row["news"] == "live" for row in self.report["countries"]
        )
        self.assertEqual(live_news, 27)
        self.assertEqual(self.rows["RU"]["news"], "unavailable")

    def test_phase5_thin_country_notes_are_locked(self):
        self.assertIn("rolling", self.rows["AT"]["notes"])
        for code in ("MX", "IL", "PT"):
            self.assertEqual(self.rows[code]["disclosure"], "live", code)
        self.assertIn("partial", self.rows["HU"]["notes"])
        self.assertIn("NewsWeb", self.rows["NO"]["notes"])
        self.assertIn("CMVM", self.rows["PT"]["notes"])

    def test_zero_sweep_us_jp_boundaries(self):
        self.assertEqual(self.rows["US"]["universe"], "partial")
        self.assertEqual(self.rows["US"]["etf_universe"], "live")
        self.assertEqual(self.rows["JP"]["universe"], "unavailable")
        self.assertEqual(self.rows["JP"]["etf_universe"], "live")
        self.assertIn("Nasdaq Trader", self.rows["US"]["notes"])
        self.assertIn("OTC/Pink", self.rows["US"]["notes"])
        self.assertIn("Listed Issues", self.rows["JP"]["notes"])


if __name__ == "__main__":
    unittest.main()
