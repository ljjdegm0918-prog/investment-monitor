"""Phase 1 integration tests: official-first merge, DE golden sample, Euronext ETF candidates."""

import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from investment_monitor.universe.global_equity_reference import (
    build_official_name_maps,
    etf_candidates_for,
    euronext_etf_candidates,
    refresh_global_equity_reference,
)


class Phase1EquityReferenceTests(unittest.TestCase):
    def setUp(self):
        self.temporary = TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.path = self.root / "global.json"
        self.saved_key = os.environ.get("EODHD_API_KEY")
        os.environ["EODHD_API_KEY"] = "test-key"
        self.addCleanup(self._restore_env)

    def _restore_env(self):
        if self.saved_key is None:
            os.environ.pop("EODHD_API_KEY", None)
        else:
            os.environ["EODHD_API_KEY"] = self.saved_key

    def _write_de_cache(self):
        cache = self.root / "de_universe.json"
        cache.write_text(json.dumps({
            "source": ["xetra_all_tradable_csv"],
            "items": [
                {"ticker": "SAP", "name": "SAP SE O.N.", "isin": "DE0007164600",
                 "board": "DAX", "exchange": "DAX",
                 "instrument_type": "CS"},
                {"ticker": "EUNL", "name": "iShares Core MSCI World ETF",
                 "isin": "IE00B4L5Y983", "board": "ETF", "exchange": "ETF",
                 "instrument_type": "ETF"},
            ],
        }), encoding="utf-8")
        return cache

    def test_official_de_entries_win_in_candidate_merge(self):
        official = build_official_name_maps(paths={"de": self._write_de_cache()})
        self.assertEqual(official["de"]["SAP"]["isin"], "DE0007164600")
        self.assertEqual(official["de"]["EUNL"]["board"], "ETF")

        def fake_eodhd(exchanges, budget):
            return [
                {"market": "de", "symbol": "SAP", "name": "wrong SAP",
                 "isin": "WRONG", "board": "wrong", "instrument_type": "stock",
                 "exchange": "XETRA", "source": "eodhd"},
                {"market": "de", "symbol": "EUNL", "name": "third-party EUNL",
                 "isin": "WRONG2", "board": "wrong", "instrument_type": "etf",
                 "exchange": "XETRA", "source": "eodhd"},
            ], 1

        payload = refresh_global_equity_reference(
            eodhd_client=fake_eodhd,
            figi_client=lambda rows: rows,
            official_name_maps=official,
            path=self.path,
        )
        by_symbol = {item["symbol"]: item for item in payload["items"]}
        self.assertEqual(by_symbol["SAP"]["name"], "SAP SE O.N.")
        self.assertEqual(by_symbol["SAP"]["isin"], "DE0007164600")
        self.assertEqual(by_symbol["SAP"]["board"], "DAX")
        self.assertEqual(by_symbol["EUNL"]["name"], "iShares Core MSCI World ETF")
        self.assertEqual(by_symbol["EUNL"]["isin"], "IE00B4L5Y983")
        self.assertEqual(by_symbol["EUNL"]["source_tier"], "third_party")

    def test_euronext_etf_candidate_entry_points(self):
        official = build_official_name_maps(paths={"de": self._write_de_cache()})

        def fake_eodhd(exchanges, budget):
            rows = []
            for market in ["be", "fr", "nl", "it", "de"]:
                rows.append({
                    "market": market, "symbol": f"ETF{market.upper()}",
                    "name": f"ETF {market}", "isin": "", "board": "",
                    "instrument_type": "etf", "exchange": exchanges.get(market, ""),
                    "source": "eodhd",
                })
            return rows, len(rows)

        payload = refresh_global_equity_reference(
            eodhd_client=fake_eodhd,
            figi_client=lambda rows: rows,
            official_name_maps=official,
            path=self.path,
        )
        euronext = euronext_etf_candidates(path=self.path)
        self.assertEqual(
            sorted(item["market"] for item in euronext),
            ["be", "fr", "it", "nl"],
        )
        self.assertEqual(
            len(etf_candidates_for("be", self.path)), 1
        )

    def test_official_also_wins_when_candidate_uses_an_alias_symbol(self):
        official = build_official_name_maps(paths={"de": self._write_de_cache()})

        def fake_eodhd(exchanges, budget):
            return [{
                "market": "de", "symbol": "SAPG", "name": "wrong alias",
                "isin": "DE0007164600", "board": "wrong",
                "instrument_type": "stock", "exchange": "XETRA",
                "source": "eodhd",
            }], 1

        payload = refresh_global_equity_reference(
            eodhd_client=fake_eodhd,
            figi_client=lambda rows: rows,
            official_name_maps=official,
            path=self.path,
        )
        item = payload["items"][0]
        self.assertEqual(item["symbol"], "SAPG")
        self.assertEqual(item["name"], "SAP SE O.N.")
        self.assertEqual(item["isin"], "DE0007164600")

    def test_missing_key_keeps_empty_honest_cache(self):
        os.environ.pop("EODHD_API_KEY", None)
        payload = refresh_global_equity_reference(path=self.path)
        self.assertEqual(payload["items"], [])
        self.assertEqual(
            payload["status"]["stages"]["eodhd"], "skipped_eodhd_no_key"
        )
        self.assertEqual(euronext_etf_candidates(path=self.path), [])


if __name__ == "__main__":
    unittest.main()
