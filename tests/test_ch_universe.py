from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from investment_monitor import (
    ChUniverseError,
    SQLiteInformationRepository,
    WebRepository,
    ch_universe_name_map,
    load_ch_universe,
    refresh_ch_universe,
    search_ch_universe,
)


class ChUniverseBoundaryTests(unittest.TestCase):
    def test_load_and_name_map_degrade_without_cache(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            cache_path = Path(temporary_directory) / "missing.json"

            self.assertIsNone(load_ch_universe(cache_path))
            self.assertEqual(ch_universe_name_map(cache_path), {})
            self.assertEqual(search_ch_universe("NESN", cache_path), [])

    def test_load_accepts_manual_cache_shape(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            cache_path = Path(temporary_directory) / "ch_universe.json"
            cache_path.write_text(
                '{"updated_at":"2026-08-10T00:00:00+00:00",'
                '"source":["manual"],"counts":{"SIX Main Standard":1},'
                '"items":[{"ticker":"NESN","name":"Nestle",'
                '"isin":"CH0038863350","board":"SIX Main Standard"}]}',
                encoding="utf-8",
            )

            payload = load_ch_universe(cache_path)
            name_map = ch_universe_name_map(cache_path)
            by_ticker = search_ch_universe("NESN", cache_path)
            by_isin = search_ch_universe("CH0038863350", cache_path)

        self.assertEqual(payload["counts"], {"SIX Main Standard": 1})
        self.assertEqual(
            name_map["NESN"],
            {
                "name": "Nestle",
                "exchange": "SIX Main Standard",
                "board": "SIX Main Standard",
                "isin": "CH0038863350",
            },
        )
        self.assertEqual(by_ticker[0]["ticker"], "NESN")
        self.assertEqual(by_isin[0]["ticker"], "NESN")

    def test_refresh_raises_instead_of_faking_a_universe(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            cache_path = Path(temporary_directory) / "ch_universe.json"

            with self.assertRaises(ChUniverseError):
                refresh_ch_universe(path=cache_path)

    def test_add_companies_batch_without_universe_is_unmapped(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            database_path = Path(temporary_directory) / "web.sqlite3"
            SQLiteInformationRepository(database_path)
            repository = WebRepository(database_path)

            result = repository.add_companies_batch(
                "NESN.SW",
                ("holdings",),
                None,
                market="ch",
                name_fallback=ch_universe_name_map(),
            )
            companies = repository.companies()

        self.assertEqual(len(result["added"]), 1)
        self.assertEqual(result["added"][0]["ticker"], "NESN")
        self.assertEqual(result["added"][0]["mapping_status"], "unmapped")
        self.assertEqual(companies[0]["market"], "ch")

    def test_universe_never_writes_information_items(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            database_path = Path(temporary_directory) / "web.sqlite3"
            repository = SQLiteInformationRepository(database_path)

            self.assertEqual(repository.count(), 0)


if __name__ == "__main__":
    unittest.main()
