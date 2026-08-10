"""Tests for the European Mutual Funds universe cache (market=emf, EMF-2).

EMF-2 spike (2026-08-10) is B2: no stable key-free ISIN-bearing European
mutual fund directory exists. ESMA registers expose a funds SOLR core
with ~212k docs (107,388 AIFMD ``funds_report`` docs; legal frameworks
AIF/EuVECA/ELTIF/EuSEF) but **no UCITS register and no ISIN field**;
``esma_registers_upreg`` is the MiFID investment-firms register.
``refresh_emf_universe()`` therefore raises instead of faking a refresh;
the cache shape is reserved for a future ISIN-bearing directory slice.
"""

from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from investment_monitor import (
    EmfUniverseError,
    SQLiteInformationRepository,
    WebRepository,
    load_emf_universe,
    refresh_emf_universe,
    search_emf_universe,
    emf_universe_name_map,
)


class EmfUniverseTests(unittest.TestCase):
    def test_refresh_raises_with_spike_evidence(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            cache_path = Path(temporary_directory) / "emf_universe.json"

            with self.assertRaises(EmfUniverseError) as caught:
                refresh_emf_universe(path=cache_path)

        message = str(caught.exception)
        self.assertIn("no stable key-free ISIN-bearing", message)
        self.assertIn("AIFMD", message)

    def test_load_and_name_map_degrade_without_cache(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            cache_path = Path(temporary_directory) / "missing.json"

            self.assertIsNone(load_emf_universe(cache_path))
            self.assertEqual(emf_universe_name_map(cache_path), {})
            self.assertEqual(search_emf_universe("LU0171254561", cache_path), [])

    def test_add_companies_batch_still_adds_emf_fund_unmapped(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            database_path = Path(temporary_directory) / "web.sqlite3"
            SQLiteInformationRepository(database_path)
            repository = WebRepository(database_path)

            result = repository.add_companies_batch(
                "LU0171254561",
                ("holdings",),
                None,
                market="emf",
                name_fallback=emf_universe_name_map(
                    Path(temporary_directory) / "missing.json"
                ),
            )

        self.assertEqual(len(result["added"]), 1)
        added = result["added"][0]
        self.assertEqual(added["ticker"], "LU0171254561")
        self.assertEqual(added["market"], "emf")
        self.assertEqual(added["mapping_status"], "unmapped")

    def test_refresh_never_writes_information_items(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            database_path = Path(temporary_directory) / "web.sqlite3"
            cache_path = Path(temporary_directory) / "emf_universe.json"
            repository = SQLiteInformationRepository(database_path)

            with self.assertRaises(EmfUniverseError):
                refresh_emf_universe(path=cache_path)

            self.assertEqual(repository.count(), 0)


if __name__ == "__main__":
    unittest.main()
