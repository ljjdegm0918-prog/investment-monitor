"""Tests for the Cboe Europe (CXE) tradeable universe cache (AEE-2).

AEE-2 spike (2026-08-10): the official Cboe Europe Symbol Data CSV
downloads (``.../symbol_data/csv/?mkt=cxe`` and ``?mkt=bxe``) are
key-free, server-side CSVs with ``Name`` (case-sensitive Cboe symbol) and
``Company Name / Description``; no ISIN column exists, so entries carry
an empty ISIN honestly. This is the first "Alternative European
Equities" venue only; Turquoise and other MTFs are deferred.
"""

from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from urllib.parse import urlsplit

from investment_monitor import (
    CxeUniverseError,
    SQLiteInformationRepository,
    WebRepository,
    load_cxe_universe,
    refresh_cxe_universe,
    search_cxe_universe,
    cxe_universe_name_map,
)


FIXTURES = Path(__file__).parent / "fixtures" / "cxe_universe"


class FakeResponse:
    def __init__(self, payload: bytes) -> None:
        self._body = payload

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return None

    def read(self) -> bytes:
        return self._body


class FakeOpener:
    """Fake opener keyed by the mkt= query parameter."""

    def __init__(self, fixtures: dict, error_markets=()) -> None:
        self.fixtures = fixtures
        self.error_markets = set(error_markets)
        self.calls: list = []

    def __call__(self, request, timeout=None):
        split = urlsplit(request.full_url)
        market = "cxe" if "mkt=cxe" in request.full_url else "bxe"
        self.calls.append((split.path, market))
        if market in self.error_markets:
            raise OSError(f"blocked {market}")
        if market in self.fixtures:
            return FakeResponse(self.fixtures[market])
        raise AssertionError(f"unexpected url: {request.full_url}")


def cxe_opener(**kwargs):
    return FakeOpener(
        {
            "cxe": (FIXTURES / "cxe_symbols.csv").read_bytes(),
            "bxe": (FIXTURES / "bxe_symbols.csv").read_bytes(),
        },
        **kwargs,
    )


class CxeUniverseRefreshTests(unittest.TestCase):
    def test_refresh_writes_cache_with_counts_and_name_map(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            cache_path = Path(temporary_directory) / "cxe_universe.json"

            payload = refresh_cxe_universe(
                path=cache_path,
                opener=cxe_opener(),
                refreshed_at="2026-08-10T00:00:00+00:00",
            )
            loaded = load_cxe_universe(cache_path)
            name_map = cxe_universe_name_map(cache_path)
            by_symbol = search_cxe_universe("AZNl", cache_path)
            by_venue = search_cxe_universe("BXE", cache_path)

        self.assertEqual(
            payload["source"],
            ["cboe_cxe_symbol_csv", "cboe_bxe_symbol_csv"],
        )
        self.assertEqual(payload["counts"], {"CXE": 3, "BXE": 3})
        self.assertEqual(payload["unique_tickers"], 5)
        self.assertEqual(loaded, payload)
        self.assertEqual(
            name_map["AZNL"],
            {
                "name": "AstraZeneca PLC",
                "exchange": "Cboe Europe CXE",
                "board": "Cboe Europe CXE",
                "isin": "",
                "venue": "CXE",
            },
        )
        self.assertEqual(name_map["SHELL"]["name"], "Shell PLC")
        self.assertEqual(name_map["ROPZ"]["board"], "Cboe Europe BXE")
        self.assertEqual(name_map["GBSPL"]["venue"], "BXE")
        azn_item = next(
            item for item in payload["items"] if item["ticker"] == "AZNL"
        )
        self.assertEqual(azn_item["venues"], ["BXE", "CXE"])
        self.assertEqual(by_symbol[0]["ticker"], "AZNL")
        self.assertEqual(
            {item["ticker"] for item in by_venue},
            {"AZNL", "ROPZ", "GBSPL"},
        )

    def test_one_book_failure_keeps_the_other(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            cache_path = Path(temporary_directory) / "cxe_universe.json"

            payload = refresh_cxe_universe(
                path=cache_path,
                opener=cxe_opener(error_markets=("bxe",)),
                refreshed_at="2026-08-10T00:00:00+00:00",
            )
            name_map = cxe_universe_name_map(cache_path)

        self.assertEqual(payload["source"], ["cboe_cxe_symbol_csv"])
        self.assertEqual(payload["counts"], {"CXE": 3})
        self.assertEqual(payload["unique_tickers"], 3)
        self.assertIn("AZNL", name_map)
        self.assertNotIn("ROPZ", name_map)

    def test_all_sources_fail_raises(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            cache_path = Path(temporary_directory) / "cxe_universe.json"

            with self.assertRaises(CxeUniverseError):
                refresh_cxe_universe(
                    path=cache_path,
                    opener=cxe_opener(error_markets=("cxe", "bxe")),
                )

    def test_load_and_name_map_degrade_without_cache(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            cache_path = Path(temporary_directory) / "missing.json"

            self.assertIsNone(load_cxe_universe(cache_path))
            self.assertEqual(cxe_universe_name_map(cache_path), {})
            self.assertEqual(search_cxe_universe("AZNl", cache_path), [])

    def test_add_companies_batch_uses_cxe_universe_name_fallback(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            database_path = Path(temporary_directory) / "web.sqlite3"
            cache_path = Path(temporary_directory) / "cxe_universe.json"
            SQLiteInformationRepository(database_path)
            repository = WebRepository(database_path)
            refresh_cxe_universe(
                path=cache_path,
                opener=cxe_opener(),
            )

            result = repository.add_companies_batch(
                "AZNl, ROPz.BXE",
                ("holdings",),
                None,
                market="cxe",
                name_fallback=cxe_universe_name_map(cache_path),
            )

        self.assertEqual(len(result["added"]), 2)
        azn = next(
            item for item in result["added"] if item["ticker"] == "AZNL"
        )
        rop = next(
            item for item in result["added"] if item["ticker"] == "ROPZ"
        )
        self.assertEqual(azn["name"], "AstraZeneca PLC")
        self.assertEqual(azn["exchange"], "Cboe Europe CXE")
        self.assertEqual(rop["name"], "Roche Holding AG")
        self.assertEqual(rop["exchange"], "Cboe Europe BXE")
        self.assertEqual(azn["mapping_status"], "unmapped")

    def test_refresh_never_writes_information_items(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            database_path = Path(temporary_directory) / "web.sqlite3"
            cache_path = Path(temporary_directory) / "cxe_universe.json"
            repository = SQLiteInformationRepository(database_path)

            refresh_cxe_universe(
                path=cache_path,
                opener=cxe_opener(),
            )

            self.assertEqual(repository.count(), 0)


if __name__ == "__main__":
    unittest.main()
