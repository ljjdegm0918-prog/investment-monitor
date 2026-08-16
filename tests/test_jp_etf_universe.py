"""Official JPX ETF universe tests (offline)."""

import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from investment_monitor.universe.jp_etf_universe import (
    JpEtfUniverseError,
    jp_etf_universe_name_map,
    parse_jp_etf_html,
    refresh_jp_etf_universe,
    search_jp_etf_universe,
)


HTML = b"""<html><body>
<table><tr><th>Other</th></tr><tr><td>ignore</td></tr></table>
<table><tr><th>Listing Date</th><th>Index</th><th>Code </th><th>Fund Name</th>
<th>Management Company</th><th>Trading Unit</th><th>Trust Fee</th><th>Market Maker(*)</th></tr>
<tr><td>Jan. 09, 2002</td><td>TOPIX</td><td>1308</td>
<td>Listed Index Fund TOPIX<div><a class="inav-btn">Indicative NAV</a></div></td>
<td>Amova Asset Management</td><td>1</td><td>0.046</td><td>yes</td></tr>
<tr><td>Feb. 25, 2009</td><td>Nikkei 225</td><td>1346</td>
<td>MAXIS NIKKEI225 ETF</td><td>Mitsubishi UFJ Asset Management</td>
<td>1</td><td>0.12</td><td>yes</td></tr>
<tr><td>Aug. 16, 2026</td><td>Example</td><td>473A</td>
<td>Example Alphanumeric ETF</td><td>Example Manager</td>
<td>1</td><td>0.10</td><td>yes</td></tr></table></body></html>"""


class _Response:
    def __init__(self, body: bytes):
        self.body = body

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return None

    def read(self):
        return self.body


class JpEtfUniverseTests(unittest.TestCase):
    def test_parser_selects_required_table_and_keeps_metadata(self):
        rows = parse_jp_etf_html(HTML.decode())
        self.assertEqual([row["ticker"] for row in rows], ["1308", "1346", "473A"])
        self.assertEqual(rows[0]["instrument_type"], "ETF")
        self.assertIn("Listed Index Fund TOPIX", rows[0]["name"])
        self.assertNotIn("Indicative NAV", rows[0]["name"])

    def test_refresh_cache_search_and_name_map(self):
        with TemporaryDirectory() as tmp:
            cache = Path(tmp) / "jp-etf.json"
            payload = refresh_jp_etf_universe(
                path=cache,
                opener=lambda *_args, **_kwargs: _Response(HTML),
                refreshed_at="2026-08-16T00:00:00+00:00",
            )
            self.assertEqual(payload["counts_by_type"], {"ETF": 3})
            self.assertEqual(json.loads(cache.read_text())["items"][0]["ticker"], "1308")
            self.assertEqual(search_jp_etf_universe("NIKKEI", cache)[0]["ticker"], "1346")
            self.assertEqual(jp_etf_universe_name_map(cache)["1308"]["exchange"], "TSE")

    def test_changed_columns_fail_closed(self):
        changed = HTML.decode().replace("Fund Name", "Product")
        with self.assertRaises(JpEtfUniverseError):
            parse_jp_etf_html(changed)

    def test_malformed_or_duplicate_rows_fail_closed(self):
        malformed = HTML.decode().replace("<td>1346</td>", "<td></td>")
        with self.assertRaises(JpEtfUniverseError):
            parse_jp_etf_html(malformed)
        for malformed_code in ("1308A", "13A08"):
            changed = HTML.decode().replace("<td>1346</td>", f"<td>{malformed_code}</td>")
            with self.subTest(code=malformed_code), self.assertRaises(JpEtfUniverseError):
                parse_jp_etf_html(changed)
        duplicate = HTML.decode().replace("<td>1346</td>", "<td>1308</td>")
        with self.assertRaises(JpEtfUniverseError):
            parse_jp_etf_html(duplicate)


if __name__ == "__main__":
    unittest.main()
