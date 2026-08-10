"""Tests for the Turquoise universe cache (market=trq, TRQ-2).

TRQ-2 re-spike (2026-08-11) is B2: no stable key-free Turquoise
directory exists (turquoise.com parked; turquoise.eu is an unrelated
company; tradeturquoise.com redirects to a JS-only LSE SPA; old
``lseg.com/turquoise/symbol/YYYYMMDD_TRQX_Instrument.csv`` URLs return
404). ``refresh_trq_universe()`` therefore raises instead of faking a
refresh or reusing the Cboe Europe CSV; the cache shape is reserved.
"""

from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from investment_monitor import (
    TrqUniverseError,
    SQLiteInformationRepository,
    WebRepository,
    load_trq_universe,
    refresh_trq_universe,
    search_trq_universe,
    trq_universe_name_map,
)


class TrqUniverseTests(unittest.TestCase):
    def test_refresh_raises_with_spike_evidence(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            cache_path = Path(temporary_directory) / "trq_universe.json"

            with self.assertRaises(TrqUniverseError) as caught:
                refresh_trq_universe(path=cache_path)

        message = str(caught.exception)
        self.assertIn("no stable key-free Turquoise directory", message)
        self.assertIn("TRQX/TQEX", message)

    def test_load_and_name_map_degrade_without_cache(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            cache_path = Path(temporary_directory) / "missing.json"

            self.assertIsNone(load_trq_universe(cache_path))
            self.assertEqual(trq_universe_name_map(cache_path), {})
            self.assertEqual(search_trq_universe("AZN", cache_path), [])

    def test_add_companies_batch_still_adds_trq_company_unmapped(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            database_path = Path(temporary_directory) / "web.sqlite3"
            SQLiteInformationRepository(database_path)
            repository = WebRepository(database_path)

            result = repository.add_companies_batch(
                "AZN.TRQ",
                ("holdings",),
                None,
                market="trq",
                name_fallback=trq_universe_name_map(
                    Path(temporary_directory) / "missing.json"
                ),
            )

        self.assertEqual(len(result["added"]), 1)
        added = result["added"][0]
        self.assertEqual(added["ticker"], "AZN")
        self.assertEqual(added["market"], "trq")
        self.assertEqual(added["mapping_status"], "unmapped")

    def test_refresh_never_writes_information_items(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            database_path = Path(temporary_directory) / "web.sqlite3"
            cache_path = Path(temporary_directory) / "trq_universe.json"
            repository = SQLiteInformationRepository(database_path)

            with self.assertRaises(TrqUniverseError):
                refresh_trq_universe(path=cache_path)

            self.assertEqual(repository.count(), 0)


if __name__ == "__main__":
    unittest.main()
