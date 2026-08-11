from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from urllib.parse import urlsplit

from investment_monitor import (
    ItUniverseError,
    SQLiteInformationRepository,
    WebRepository,
    it_universe_name_map,
    load_it_universe,
    refresh_it_universe,
    search_it_universe,
)


FIXTURES = Path(__file__).parent / "fixtures" / "it_universe"


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
                FIXTURES / "euronext_it_sample.csv"
            ).read_bytes()
        },
        **kwargs,
    )


class ItUniverseRefreshTests(unittest.TestCase):
    def test_refresh_writes_cache_with_counts_and_name_map(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            cache_path = Path(temporary_directory) / "it_universe.json"

            payload = refresh_it_universe(
                path=cache_path,
                opener=directory_opener(),
                refreshed_at="2026-08-10T00:00:00+00:00",
            )
            loaded = load_it_universe(cache_path)
            name_map = it_universe_name_map(cache_path)
            by_ticker = search_it_universe("ENI", cache_path)
            by_isin = search_it_universe("IT0005239360", cache_path)

        self.assertEqual(payload["source"], ["euronext_live_csv"])
        self.assertEqual(
            payload["counts"],
            {
                "Euronext Milan": 3,
                "Euronext Growth Milan": 1,
            },
        )
        self.assertEqual(loaded, payload)
        self.assertEqual(
            name_map["ENI"],
            {
                "name": "ENI",
                "exchange": "Euronext Milan",
                "board": "Euronext Milan",
                "isin": "IT0003132476",
            },
        )
        self.assertEqual(name_map["AIM"]["exchange"], "Euronext Growth Milan")
        self.assertEqual(by_ticker[0]["ticker"], "ENI")
        self.assertEqual(by_isin[0]["ticker"], "UCG")

    def test_all_sources_fail_raises(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            cache_path = Path(temporary_directory) / "it_universe.json"

            with self.assertRaises(ItUniverseError):
                refresh_it_universe(
                    path=cache_path,
                    opener=directory_opener(
                        error_paths=("/en/pd_es/data/stocks/download",)
                    ),
                )

    def test_load_and_name_map_degrade_without_cache(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            cache_path = Path(temporary_directory) / "missing.json"

            self.assertIsNone(load_it_universe(cache_path))
            self.assertEqual(it_universe_name_map(cache_path), {})
            self.assertEqual(search_it_universe("ENI", cache_path), [])

    def test_add_companies_batch_uses_it_universe_name_fallback(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            database_path = Path(temporary_directory) / "web.sqlite3"
            cache_path = Path(temporary_directory) / "it_universe.json"
            SQLiteInformationRepository(database_path)
            repository = WebRepository(database_path)
            refresh_it_universe(
                path=cache_path,
                opener=directory_opener(),
            )

            result = repository.add_companies_batch(
                "ENI.MI, UCG",
                ("holdings",),
                None,
                market="it",
                name_fallback=it_universe_name_map(cache_path),
            )

        self.assertEqual(len(result["added"]), 2)
        eni = next(
            item for item in result["added"] if item["ticker"] == "ENI"
        )
        ucg = next(
            item for item in result["added"] if item["ticker"] == "UCG"
        )
        self.assertEqual(eni["name"], "ENI")
        self.assertEqual(eni["exchange"], "Euronext Milan")
        self.assertEqual(ucg["name"], "UNICREDIT")
        self.assertEqual(eni["mapping_status"], "unmapped")

    def test_refresh_never_writes_information_items(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            database_path = Path(temporary_directory) / "web.sqlite3"
            cache_path = Path(temporary_directory) / "it_universe.json"
            repository = SQLiteInformationRepository(database_path)

            refresh_it_universe(
                path=cache_path,
                opener=directory_opener(),
            )

            self.assertEqual(repository.count(), 0)


if __name__ == "__main__":
    unittest.main()
