"""P5-2 ETF issuer-disclosure skeleton tests."""

import unittest

from investment_monitor.universe.coverage_report import coverage_report


class EtfDisclosureSkeletonTests(unittest.TestCase):
    def setUp(self):
        self.report = coverage_report()
        self.rows = {
            row["country_code"]: row for row in self.report["countries"]
        }

    def test_every_country_reports_etf_disclosure_field(self):
        for row in self.report["countries"]:
            self.assertIn(
                row["etf_disclosure"],
                ("live", "partial", "stub", "unavailable"),
            )

    def test_no_equity_disclosure_is_mislabeled_as_etf_live(self):
        # 现状：无免 key ETF 发行人文件/公告源接入，必须全部 unavailable；
        # 绝不能把 DE eqs_dgap 等股权公告标成 ETF 披露 LIVE。
        for code, row in self.rows.items():
            self.assertEqual(
                row["etf_disclosure"], "unavailable", code
            )

    def test_de_etf_universe_live_but_disclosure_still_honest(self):
        self.assertEqual(self.rows["DE"]["etf_universe"], "live")
        self.assertEqual(self.rows["DE"]["etf_disclosure"], "unavailable")
        self.assertIn(
            "ETF issuer disclosure unavailable",
            self.rows["DE"]["notes"],
        )


if __name__ == "__main__":
    unittest.main()
