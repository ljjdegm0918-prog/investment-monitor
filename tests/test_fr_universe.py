from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from urllib.parse import urlsplit

from investment_monitor import (
    FrUniverseError,
    SQLiteInformationRepository,
    WebRepository,
    fr_universe_name_map,
    load_fr_universe,
    refresh_fr_universe,
    search_fr_universe,
)


FIXTURES = Path(__file__).parent / "fixtures" / "fr_universe"


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
    def __init__(self, fixtures: dict, error_paths=()) -> None:
        self.fixtures = fixtures
        self.error_paths = set(error_paths)
        self.calls: list = []

    def __call__(self, request, timeout=None):
        path = urlsplit(request.full_url).path
        self.calls.append(path)
        if path in self.error_paths:
            raise OSError(f"blocked {path}")
        if path in self.fixtures:
            return FakeResponse(self.fixtures[path])
        raise AssertionError(f"unexpected url: {request.full_url}")


def directory_opener(**kwargs):
    return FakeOpener(
        {
            "/en/pd_es/data/stocks/download": (
                FIXTURES / "euronext_fr_sample.csv"
            ).read_bytes()
        },
        **kwargs,
    )


class FrUniverseRefreshTests(unittest.TestCase):
    def test_refresh_writes_cache_with_counts_and_name_map(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            cache_path = Path(temporary_directory) / "fr_universe.json"

            payload = refresh_fr_universe(
                path=cache_path,
                opener=directory_opener(),
                refreshed_at="2026-08-09T00:00:00+00:00",
            )
            loaded = load_fr_universe(cache_path)
            name_map = fr_universe_name_map(cache_path)
            by_ticker = search_fr_universe("MC", cache_path)
            by_isin = search_fr_universe("FR0013341781", cache_path)

        self.assertEqual(payload["source"], ["euronext_live_csv"])
        self.assertEqual(
            payload["counts"],
            {
                "Euronext Paris": 2,
                "Euronext Growth Paris": 2,
                "Euronext Access Paris": 1,
                "Euronext Paris, Brussels": 1,
            },
        )
        self.assertEqual(loaded, payload)
        self.assertEqual(
            name_map["MC"],
            {
                "name": "LVMH",
                "exchange": "Euronext Paris",
                "board": "Euronext Paris",
                "isin": "FR0000121014",
            },
        )
        self.assertEqual(
            name_map["AL2SI"]["exchange"], "Euronext Growth Paris"
        )
        self.assertEqual(name_map["AL2SI"]["isin"], "FR0013341781")
        self.assertEqual(
            name_map["MLACT"]["exchange"], "Euronext Access Paris"
        )
        self.assertEqual(
            name_map["TTE"]["exchange"], "Euronext Paris, Brussels"
        )
        self.assertNotIn("1MC", name_map)  # Global Equity Market decoy
        self.assertNotIn("2MC", name_map)  # Trading After Hours decoy
        self.assertNotIn("4SAN", name_map)  # EuroTLX decoy
        self.assertNotIn("NMC", name_map)  # Expert Market / empty symbol
        self.assertEqual(by_ticker[0]["ticker"], "MC")
        self.assertEqual(by_isin[0]["ticker"], "AL2SI")

    def test_all_sources_fail_raises(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            cache_path = Path(temporary_directory) / "fr_universe.json"

            with self.assertRaises(FrUniverseError):
                refresh_fr_universe(
                    path=cache_path,
                    opener=directory_opener(
                        error_paths=("/en/pd_es/data/stocks/download",)
                    ),
                )

    def test_load_and_name_map_degrade_without_cache(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            cache_path = Path(temporary_directory) / "missing.json"

            self.assertIsNone(load_fr_universe(cache_path))
            self.assertEqual(fr_universe_name_map(cache_path), {})
            self.assertEqual(search_fr_universe("MC", cache_path), [])

    def test_add_companies_batch_uses_fr_universe_name_fallback(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            database_path = Path(temporary_directory) / "web.sqlite3"
            cache_path = Path(temporary_directory) / "fr_universe.json"
            SQLiteInformationRepository(database_path)
            repository = WebRepository(database_path)
            refresh_fr_universe(
                path=cache_path,
                opener=directory_opener(),
            )

            result = repository.add_companies_batch(
                "MC.PA, AL2SI",
                ("holdings",),
                None,
                market="fr",
                name_fallback=fr_universe_name_map(cache_path),
            )

        self.assertEqual(len(result["added"]), 2)
        mc = next(item for item in result["added"] if item["ticker"] == "MC")
        al2si = next(
            item for item in result["added"] if item["ticker"] == "AL2SI"
        )
        self.assertEqual(mc["name"], "LVMH")
        self.assertEqual(mc["exchange"], "Euronext Paris")
        self.assertEqual(al2si["name"], "2CRSI")
        self.assertEqual(al2si["exchange"], "Euronext Growth Paris")
        self.assertEqual(mc["mapping_status"], "unmapped")

    def test_refresh_never_writes_information_items(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            database_path = Path(temporary_directory) / "web.sqlite3"
            cache_path = Path(temporary_directory) / "fr_universe.json"
            repository = SQLiteInformationRepository(database_path)

            refresh_fr_universe(
                path=cache_path,
                opener=directory_opener(),
            )

            self.assertEqual(repository.count(), 0)


if __name__ == "__main__":
    unittest.main()
