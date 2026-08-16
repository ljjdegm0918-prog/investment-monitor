"""Nasdaq Baltic universe cache tests (fixture XLSX, no network)."""

import io
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
import zipfile

from investment_monitor.universe.nasdaq_baltic_universe import (
    BalticUniverseError,
    baltic_universe_name_map,
    load_baltic_universe,
    refresh_baltic_universe,
    search_baltic_universe,
)

NS = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"


def cell(reference, shared_index):
    return f'<c r="{reference}" t="s"><v>{shared_index}</v></c>'


def make_xlsx(rows):
    strings = []
    string_index = {}
    for row in rows:
        for value in row:
            if value not in string_index:
                string_index[value] = len(strings)
                strings.append(value)

    shared = "".join(
        f"<si><t>{value}</t></si>" for value in strings
    )
    shared_xml = (
        f'<sst xmlns="{NS}" count="{len(strings)}" uniqueCount="{len(strings)}">{shared}</sst>'
    )
    sheet_rows = []
    for row_number, values in enumerate(rows, start=1):
        cells = []
        for column_index, value in enumerate(values):
            reference = f"{chr(ord('A') + column_index)}{row_number}"
            cells.append(cell(reference, string_index[value]))
        sheet_rows.append(f'<row r="{row_number}">{"".join(cells)}</row>')
    sheet_xml = (
        f'<worksheet xmlns="{NS}"><sheetData>{"".join(sheet_rows)}</sheetData></worksheet>'
    )
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("xl/sharedStrings.xml", shared_xml)
        archive.writestr("xl/worksheets/sheet1.xml", sheet_xml)
    return buffer.getvalue()


class FakeResponse:
    def __init__(self, payload):
        self._payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return None

    def read(self):
        return self._payload


class BalticUniverseTests(unittest.TestCase):
    def setUp(self):
        self.temporary = TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.old_cwd = Path.cwd()
        self.addCleanup(lambda: __import__("os").chdir(self.old_cwd))
        __import__("os").chdir(self.root)
        self.xlsx = make_xlsx([
            ["Ticker", "Name", "ISIN", "Currency", "MarketPlace", "List/segment"],
            ["TAL1T", "Tallinna Kaubamaja Grupp", "EE3100004466", "EUR", "TLN", "Baltic Main List"],
            ["SAF1R", "SAF Tehnika", "LV0000101129", "EUR", "RIG", "Baltic Main List"],
            ["TEL1L", "Telia Lietuva", "LT0000123911", "EUR", "VLN", "Baltic Main List"],
            ["ERIC", "Ericsson", "SE0000108656", "SEK", "STO", "Main Market"],
        ])

    def refresh(self):
        return refresh_baltic_universe(
            opener=lambda request, timeout: FakeResponse(self.xlsx),
        )

    def test_refresh_partitions_by_market_place_and_ignores_foreign(self):
        payload = self.refresh()
        self.assertEqual(set(payload["markets"]), {"ee", "lv", "lt"})
        self.assertEqual([e["ticker"] for e in payload["markets"]["ee"]], ["TAL1T"])
        self.assertEqual([e["ticker"] for e in payload["markets"]["lv"]], ["SAF1R"])
        self.assertEqual([e["ticker"] for e in payload["markets"]["lt"]], ["TEL1L"])

    def test_name_map_shapes_and_search(self):
        self.refresh()
        name_map = baltic_universe_name_map("ee")
        self.assertEqual(name_map, {
            "TAL1T": {
                "name": "Tallinna Kaubamaja Grupp",
                "isin": "EE3100004466",
                "board": "Baltic Main List",
            }
        })
        hits = search_baltic_universe("ee", "kaubamaja")
        self.assertEqual([e["ticker"] for e in hits], ["TAL1T"])

    def test_load_returns_none_without_cache(self):
        self.assertIsNone(load_baltic_universe(self.root / "missing.json"))

    def test_invalid_xlsx_raises_baltic_universe_error(self):
        with self.assertRaises(BalticUniverseError):
            refresh_baltic_universe(
                opener=lambda request, timeout: FakeResponse(b"not-a-zip"),
            )


if __name__ == "__main__":
    unittest.main()
