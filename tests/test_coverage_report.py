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

        for code in ("AT", "MX"):
            row = self.rows[code]
            self.assertEqual(row["universe"], "stub")
            self.assertEqual(row["disclosure"], "stub")

        ru = self.rows["RU"]
        self.assertEqual(ru["trading_status"], "suspended")
        self.assertEqual(ru["universe"], "partial")
        self.assertEqual(ru["disclosure"], "unavailable")
        self.assertEqual(ru["news"], "unavailable")
        self.assertEqual(ru["source_tier_summary"], "mixed")

    def test_boundary_stubs_are_never_live(self):
        for code in ("AT", "HU", "IL", "MX", "NO", "PT"):
            self.assertEqual(
                self.rows[code]["disclosure"], "stub", f"{code} disclosure"
            )
        for code in ("AT", "CH", "HU", "IL", "MX", "SE", "SG"):
            self.assertNotEqual(self.rows[code]["universe"], "live", code)

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


if __name__ == "__main__":
    unittest.main()
