from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from investment_monitor import (
    SeUniverseError,
    SQLiteInformationRepository,
    WebRepository,
    load_se_universe,
    refresh_se_universe,
    search_se_universe,
    se_universe_name_map,
)


class SeUniverseBoundaryTests(unittest.TestCase):
    def test_load_and_name_map_degrade_without_cache(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            cache_path = Path(temporary_directory) / "missing.json"

            self.assertIsNone(load_se_universe(cache_path))
            self.assertEqual(se_universe_name_map(cache_path), {})
            self.assertEqual(search_se_universe("ERIC-B", cache_path), [])

    def test_load_accepts_manual_cache_shape(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            cache_path = Path(temporary_directory) / "se_universe.json"
            cache_path.write_text(
                '{"updated_at":"2026-08-10T00:00:00+00:00",'
                '"source":["manual"],"counts":{"Nasdaq Stockholm Main Market":2},'
                '"items":[{"ticker":"ERIC-B","name":"Telefonaktiebolaget LM '
                'Ericsson","isin":"SE0000108656","board":"Nasdaq Stockholm '
                'Main Market"},{"ticker":"VOLV-B","name":"AB Volvo",'
                '"isin":"SE0000115425","board":"Nasdaq Stockholm Main Market"}]}',
                encoding="utf-8",
            )

            payload = load_se_universe(cache_path)
            name_map = se_universe_name_map(cache_path)
            by_ticker = search_se_universe("ERIC-B", cache_path)
            by_isin = search_se_universe("SE0000108656", cache_path)

        self.assertEqual(payload["counts"], {"Nasdaq Stockholm Main Market": 2})
        self.assertEqual(
            name_map["ERIC-B"],
            {
                "name": "Telefonaktiebolaget LM Ericsson",
                "exchange": "Nasdaq Stockholm Main Market",
                "board": "Nasdaq Stockholm Main Market",
                "isin": "SE0000108656",
            },
        )
        self.assertEqual(by_ticker[0]["ticker"], "ERIC-B")
        self.assertEqual(by_isin[0]["ticker"], "ERIC-B")

    def test_refresh_raises_instead_of_faking_a_universe(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            cache_path = Path(temporary_directory) / "se_universe.json"

            with self.assertRaises(SeUniverseError):
                refresh_se_universe(path=cache_path)

    def test_add_companies_batch_without_universe_is_unmapped(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            database_path = Path(temporary_directory) / "web.sqlite3"
            SQLiteInformationRepository(database_path)
            repository = WebRepository(database_path)

            result = repository.add_companies_batch(
                "ERIC-B.ST",
                ("holdings",),
                None,
                market="se",
                name_fallback=se_universe_name_map(),
            )
            companies = repository.companies()

        self.assertEqual(len(result["added"]), 1)
        self.assertEqual(result["added"][0]["ticker"], "ERIC-B")
        self.assertEqual(result["added"][0]["mapping_status"], "unmapped")
        self.assertEqual(companies[0]["market"], "se")

    def test_add_companies_batch_uses_se_universe_name_fallback(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            database_path = Path(temporary_directory) / "web.sqlite3"
            cache_path = Path(temporary_directory) / "se_universe.json"
            cache_path.write_text(
                '{"updated_at":"2026-08-10T00:00:00+00:00","source":["manual"],'
                '"counts":{"Nasdaq Stockholm Main Market":1},'
                '"items":[{"ticker":"ERIC-B",'
                '"name":"Telefonaktiebolaget LM Ericsson",'
                '"isin":"SE0000108656","board":"Nasdaq Stockholm Main Market"}]}',
                encoding="utf-8",
            )
            SQLiteInformationRepository(database_path)
            repository = WebRepository(database_path)

            result = repository.add_companies_batch(
                "ERIC-B.ST",
                ("holdings",),
                None,
                market="se",
                name_fallback=se_universe_name_map(cache_path),
            )

        self.assertEqual(len(result["added"]), 1)
        self.assertEqual(result["added"][0]["ticker"], "ERIC-B")
        self.assertEqual(
            result["added"][0]["name"],
            "Telefonaktiebolaget LM Ericsson",
        )
        self.assertEqual(
            result["added"][0]["exchange"],
            "Nasdaq Stockholm Main Market",
        )
        self.assertEqual(result["added"][0]["mapping_status"], "unmapped")

    def test_universe_never_writes_information_items(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            database_path = Path(temporary_directory) / "web.sqlite3"
            repository = SQLiteInformationRepository(database_path)

            self.assertEqual(repository.count(), 0)


if __name__ == "__main__":
    unittest.main()
