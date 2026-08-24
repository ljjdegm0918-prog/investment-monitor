"""P0-3 coverage API tests (offline web app fixture)."""

import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from investment_monitor.web import WebApplication


class _NoopRunner:
    def __call__(self, **kwargs):
        raise AssertionError("collection must not run in this test")


class CoverageApiTests(unittest.TestCase):
    def setUp(self):
        self.temporary = TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.project_root = Path(self.temporary.name)
        (self.project_root / "config").mkdir()
        (self.project_root / "data").mkdir()
        (self.project_root / "config" / "settings.yaml").write_text(
            "enabled_sources:\n  - sec\ndatabase_path: ../data/web.sqlite3\n",
            encoding="utf-8",
        )
        (self.project_root / "config" / "universe.csv").write_text(
            "ticker,list_type\nAAPL,holdings\n", encoding="utf-8"
        )
        self.application = WebApplication(
            self.project_root,
            collection_runner=_NoopRunner(),
        )

    def test_coverage_payload_counts_and_shapes(self):
        response = self.application.handle("GET", "/api/coverage")
        self.assertEqual(response.status, 200)
        payload = json.loads(response.body.decode("utf-8"))
        self.assertEqual(payload["catalog"]["countries"], 28)
        self.assertEqual(payload["catalog"]["venues"], 87)
        report = payload["report"]
        self.assertEqual(report["summary"]["countries"], 28)
        self.assertEqual(report["summary"]["venues"], 87)
        rows = {row["country_code"]: row for row in report["countries"]}
        self.assertNotIn("trading_status", rows["RU"])
        self.assertFalse(report["scope"]["broker_runtime_dependency"])
        self.assertFalse(report["scope"]["broker_account_required"])
        self.assertFalse(report["scope"]["trading_capability_assessed"])
        self.assertEqual(payload["canada"]["maximum_rating"], "high")
        self.assertEqual(payload["canada"]["rating"], "unavailable")
        self.assertEqual(payload["singapore"]["maximum_rating"], "high")
        self.assertEqual(payload["singapore"]["rating"], "unavailable")
        self.assertEqual(
            set(payload["canada"]["exchange_coverage"]),
            {"TSX", "TSXV", "CSE"},
        )
        self.assertEqual(rows["DE"]["etf_universe"], "live")
        for required in (
            "universe", "disclosure", "news", "etf_universe",
            "etf_disclosure", "source_tier_summary", "venue_count",
        ):
            self.assertIn(required, rows["US"])

    def test_payload_contains_no_credentials(self):
        response = self.application.handle("GET", "/api/coverage")
        text = response.body.decode("utf-8")
        for forbidden in ("token", "api_key", "IBKR_WEB_API_TOKEN"):
            self.assertNotIn(forbidden.lower(), text.lower())


if __name__ == "__main__":
    unittest.main()
