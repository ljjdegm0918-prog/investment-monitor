"""Web-layer global equity reference fallback tests (offline)."""

import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from investment_monitor.web import WebApplication


class _NoopRunner:
    def __call__(self, **kwargs):
        raise AssertionError("collection must not run in this test")


class GlobalReferenceWebFallbackTests(unittest.TestCase):
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
        cache_directory = self.project_root / ".cache" / "investment_monitor"
        cache_directory.mkdir(parents=True)
        self.application = WebApplication(
            self.project_root,
            collection_runner=_NoopRunner(),
        )

    def _write_reference_cache(self):
        payload = {
            "source_tier": "third_party",
            "items": [
                {
                    "market": "be", "symbol": "ETFBRU", "name": "Brussels ETF",
                    "isin": "", "board": "ETF", "exchange": "BRU",
                    "instrument_type": "etf",
                },
                {
                    "market": "be", "symbol": "AGS", "name": "wrong ageas",
                    "isin": "", "board": "ETF", "exchange": "BRU",
                    "instrument_type": "etf",
                },
            ],
        }
        path = self.project_root / ".cache" / "investment_monitor" / "global_equity_reference.json"
        path.write_text(json.dumps(payload), encoding="utf-8")
        return path

    def test_reference_fills_below_official_map(self):
        self._write_reference_cache()
        official = {"AGS": {"name": "ageas SA/NV", "isin": "BE0974264930",
                            "board": "Euronext Brussels"}}
        merged = self.application._with_global_reference_fallback("be", official)
        self.assertIn("ETFBRU", merged)
        self.assertEqual(merged["ETFBRU"]["name"], "Brussels ETF")
        self.assertEqual(merged["ETFBRU"]["instrument_type"], "etf")
        # 官方命中保留，第三方同名条目不覆盖。
        self.assertEqual(merged["AGS"]["name"], "ageas SA/NV")

    def test_cold_reference_cache_returns_official_unchanged(self):
        official = {"AGS": {"name": "ageas SA/NV", "isin": "BE0974264930",
                            "board": "Euronext Brussels"}}
        merged = self.application._with_global_reference_fallback("be", official)
        self.assertEqual(merged, official)

    def test_symbol_is_normalised_like_add_company(self):
        self._write_reference_cache()
        merged = self.application._with_global_reference_fallback("be", None)
        # AGS.BR 在 add-company 会归一成 AGS；参考层符号同样要可命中。
        self.assertEqual(
            self.application._normalize_global_reference_symbol("be", "AGS.BR"),
            "AGS",
        )
        self.assertIn("AGS", merged)


if __name__ == "__main__":
    unittest.main()
