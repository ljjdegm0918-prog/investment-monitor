"""Global equity reference contract and pipeline tests."""

import os
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from investment_monitor.universe.global_equity_reference import (
    empty_payload,
    etf_candidates_for,
    load_global_equity_reference,
    refresh_global_equity_reference,
    search_global_equity_reference,
)


class GlobalEquityReferenceTests(unittest.TestCase):
    def setUp(self):
        self.temporary = TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.path = self.root / "global.json"

    @staticmethod
    def _restore_env(name, saved):
        if saved is None:
            os.environ.pop(name, None)
        else:
            os.environ[name] = saved

    def test_refresh_without_keys_is_non_fatal_and_reports_status(self):
        saved = os.environ.get("EODHD_API_KEY")
        os.environ.pop("EODHD_API_KEY", None)
        self.addCleanup(self._restore_env, "EODHD_API_KEY", saved)
        payload = refresh_global_equity_reference(path=self.path)
        self.assertEqual(payload["source_tier"], "third_party")
        self.assertEqual(payload["status"]["stages"]["eodhd"], "skipped_eodhd_no_key")
        self.assertEqual(payload["status"]["stages"]["openfigi"], "skipped_empty")
        self.assertEqual(payload["status"]["stages"]["twelve"], "skipped_twelve_no_key")
        self.assertEqual(payload["items"], [])
        self.assertIsNotNone(load_global_equity_reference(self.path))

    def test_official_entries_win_for_same_symbol(self):
        saved = os.environ.get("EODHD_API_KEY")
        os.environ["EODHD_API_KEY"] = "test-key"
        self.addCleanup(self._restore_env, "EODHD_API_KEY", saved)
        official = {"de": {"SAP": {"name": "SAP SE", "isin": "DE0007164600", "board": "Xetra CS"}}}
        def fake_eodhd(exchanges, budget):
            return [{
                "market": "de", "symbol": "SAP", "isin": "WRONG",
                "instrument_type": "stock", "name": "third-party SAP",
            }], 1
        payload = refresh_global_equity_reference(
            eodhd_client=fake_eodhd,
            figi_client=lambda rows: rows,
            official_name_maps=official,
            path=self.path,
        )
        item = payload["items"][0]
        self.assertEqual(item["isin"], "DE0007164600")
        self.assertEqual(item["name"], "SAP SE")
        self.assertEqual(item["source_tier"], "third_party")
        self.assertEqual(payload["daily_budget"]["used_calls"], 1)

    def test_etf_candidates_filter(self):
        payload = empty_payload()
        payload["items"] = [
            {"market": "de", "symbol": "EUNL", "instrument_type": "etf", "isin": "IE00B4L5Y983", "name": "EUNL", "source_tier": "third_party"},
            {"market": "de", "symbol": "SAP", "instrument_type": "stock", "isin": "DE0007164600", "name": "SAP SE", "source_tier": "third_party"},
        ]
        import json
        self.path.write_text(json.dumps(payload), encoding="utf-8")
        etfs = etf_candidates_for("de", self.path)
        self.assertEqual([e["symbol"] for e in etfs], ["EUNL"])
        self.assertEqual(
            search_global_equity_reference("SAP", market="de", path=self.path)[0]["instrument_type"],
            "stock",
        )

    def test_budget_resets_on_new_day(self):
        from investment_monitor.universe.global_equity_reference import (
            _load_or_new_budget,
        )
        import json
        payload = empty_payload()
        payload["daily_budget"] = {"limit": 20, "date": "2000-01-01", "used_calls": 19, "refreshed_exchanges": ["XETRA"]}
        self.path.write_text(json.dumps(payload), encoding="utf-8")
        budget = _load_or_new_budget(self.path)
        self.assertEqual(budget["used_calls"], 0)
        self.assertEqual(budget["refreshed_exchanges"], [])


if __name__ == "__main__":
    unittest.main()
