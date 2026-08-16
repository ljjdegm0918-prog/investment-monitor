"""Euronext NO/PT universe tests (fixture CSV, no network)."""

from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from investment_monitor.universe.no_universe import (
    NoUniverseError,
    no_universe_name_map,
    refresh_no_universe,
)
from investment_monitor.universe.pt_universe import (
    PtUniverseError,
    pt_universe_name_map,
    refresh_pt_universe,
)

CSV = (
    "Name;ISIN;Symbol;Market;Currency\n"
    "Equinor ASA;NO0010096985;EQNR;Oslo Børs;NOK\n"
    "Storebrand ASA;NO0003053605;STB;Oslo Børs;NOK\n"
    "Aker Horizons ASA;NO0010921232;AKH;Euronext Growth Oslo;NOK\n"
    "EDP Energias;PTEDP0AM0009;EDP;Euronext Lisbon;EUR\n"
    "Galp Energia;PTGAL0AM0009;GALP;Euronext Lisbon;EUR\n"
    "Sonae SGPS;PTSON0AM0001;SON;Euronext Access Lisbon;EUR\n"
    "Shell Plc;GB00BP6MXD84;SHELL;Euronext Amsterdam;EUR\n"
    "LVMH;FR0000121014;MC;Euronext Paris;EUR\n"
)


class FakeResponse:
    def __init__(self, text):
        self._text = text

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return None

    def read(self):
        return self._text.encode("utf-8")


class EuronextNoPtUniverseTests(unittest.TestCase):
    def setUp(self):
        self.temporary = TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)

    def refresh(self, func, name):
        return func(
            path=self.root / f"{name}.json",
            opener=lambda request, timeout: FakeResponse(CSV),
        )

    def test_no_universe_keeps_only_oslo_rows(self):
        payload = self.refresh(refresh_no_universe, "no")
        tickers = [item["ticker"] for item in payload["items"]]
        self.assertEqual(tickers, ["AKH", "EQNR", "STB"])
        name_map = no_universe_name_map(self.root / "no.json")
        self.assertEqual(name_map["EQNR"]["isin"], "NO0010096985")
        self.assertEqual(name_map["EQNR"]["board"], "Oslo Børs")

    def test_pt_universe_keeps_only_lisbon_rows(self):
        payload = self.refresh(refresh_pt_universe, "pt")
        tickers = [item["ticker"] for item in payload["items"]]
        self.assertEqual(tickers, ["EDP", "GALP", "SON"])
        name_map = pt_universe_name_map(self.root / "pt.json")
        self.assertEqual(name_map["EDP"]["isin"], "PTEDP0AM0009")

    def test_empty_venue_raises(self):
        with self.assertRaises(NoUniverseError):
            refresh_no_universe(
                path=self.root / "empty-no.json",
                opener=lambda request, timeout: FakeResponse(
                    "Name;ISIN;Symbol;Market;Currency\n"
                    "Shell Plc;GB00BP6MXD84;SHELL;Euronext Amsterdam;EUR\n"
                ),
            )
        with self.assertRaises(PtUniverseError):
            refresh_pt_universe(
                path=self.root / "empty-pt.json",
                opener=lambda request, timeout: FakeResponse(
                    "Name;ISIN;Symbol;Market;Currency\n"
                    "Shell Plc;GB00BP6MXD84;SHELL;Euronext Amsterdam;EUR\n"
                ),
            )


if __name__ == "__main__":
    unittest.main()
