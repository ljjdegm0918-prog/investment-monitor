"""P5-4 quarterly catalog diff tool tests."""

import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from investment_monitor.catalog_diff import compare_catalogs, run
from investment_monitor.universe.exchange_catalog import load_exchange_catalog


class CatalogDiffTests(unittest.TestCase):
    def test_current_catalog_summary_is_frozen(self):
        report, code = run(["--snapshot", str(_missing())])
        self.assertEqual(code, 2)  # no snapshot: exit 2 with usage hint

    def test_write_snapshot_then_diff_is_clean(self):
        with TemporaryDirectory() as tmp:
            snapshot = Path(tmp) / "snapshot.json"
            report, code = run(["--snapshot", str(snapshot), "--write-snapshot"])
            self.assertEqual(code, 0)
            report, code = run(["--snapshot", str(snapshot), "--json"])
            self.assertEqual(code, 0)
            self.assertEqual(report["current"]["countries"], 28)
            self.assertEqual(report["current"]["venues"], 87)
            self.assertEqual(report["countries"]["changed"], [])
            self.assertEqual(report["venues"]["changed"], [])

    def test_compare_catalogs_detects_venue_change(self):
        current = dict(load_exchange_catalog())
        previous = json.loads(json.dumps(current))
        previous["venues"][0]["venue_name"] = "OLD NAME"
        previous["venues"] = previous["venues"][:-1]
        report = compare_catalogs(previous, current)
        self.assertEqual(len(report["venues"]["removed"]), 0)
        self.assertEqual(len(report["venues"]["added"]), 1)
        self.assertEqual(len(report["venues"]["changed"]), 1)


def _missing() -> Path:
    return Path(__file__).parent / "does-not-exist-snapshot.json"


if __name__ == "__main__":
    unittest.main()
