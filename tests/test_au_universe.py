from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from urllib.parse import urlsplit

from investment_monitor import (
    AuUniverseError,
    SQLiteInformationRepository,
    WebRepository,
    au_universe_name_map,
    load_au_universe,
    refresh_au_universe,
    search_au_universe,
)


FIXTURES = Path(__file__).parent / "fixtures" / "au_universe"


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
            "/asx-research/1.0/companies/directory": (
                FIXTURES / "asx_directory.json"
            ).read_bytes()
        },
        **kwargs,
    )


class AuUniverseRefreshTests(unittest.TestCase):
    def test_refresh_writes_cache_with_counts_and_name_map(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            cache_path = Path(temporary_directory) / "au_universe.json"

            payload = refresh_au_universe(
                path=cache_path,
                opener=directory_opener(),
                refreshed_at="2026-08-08T00:00:00+00:00",
            )
            loaded = load_au_universe(cache_path)
            name_map = au_universe_name_map(cache_path)
            by_ticker = search_au_universe("BHP", cache_path)
            by_name = search_au_universe("333D", cache_path)

        self.assertEqual(payload["source"], ["asx_directory"])
        self.assertEqual(payload["counts"], {"ASX": 4})
        self.assertEqual(loaded, payload)
        self.assertEqual(
            name_map["BHP"],
            {"name": "BHP GROUP LIMITED", "exchange": "ASX"},
        )
        self.assertEqual(name_map["CBA"]["exchange"], "ASX")
        self.assertEqual(name_map["10X"]["exchange"], "ASX")
        self.assertEqual(
            name_map["T3D"],
            {"name": "333D LIMITED", "exchange": "ASX"},
        )
        self.assertEqual(by_ticker[0]["ticker"], "BHP")
        self.assertEqual(by_name[0]["ticker"], "T3D")

    def test_all_sources_fail_raises(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            cache_path = Path(temporary_directory) / "au_universe.json"

            with self.assertRaises(AuUniverseError):
                refresh_au_universe(
                    path=cache_path,
                    opener=directory_opener(
                        error_paths=(
                            "/asx-research/1.0/companies/directory",
                        )
                    ),
                )

    def test_load_and_name_map_degrade_without_cache(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            cache_path = Path(temporary_directory) / "missing.json"

            self.assertIsNone(load_au_universe(cache_path))
            self.assertEqual(au_universe_name_map(cache_path), {})
            self.assertEqual(search_au_universe("BHP", cache_path), [])

    def test_add_companies_batch_uses_au_universe_name_fallback(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            database_path = Path(temporary_directory) / "web.sqlite3"
            cache_path = Path(temporary_directory) / "au_universe.json"
            SQLiteInformationRepository(database_path)
            repository = WebRepository(database_path)
            refresh_au_universe(
                path=cache_path,
                opener=directory_opener(),
            )

            result = repository.add_companies_batch(
                "BHP.AX, CBA",
                ("holdings",),
                None,
                market="au",
                name_fallback=au_universe_name_map(cache_path),
            )

        self.assertEqual(len(result["added"]), 2)
        bhp = next(
            item for item in result["added"] if item["ticker"] == "BHP"
        )
        cba = next(
            item for item in result["added"] if item["ticker"] == "CBA"
        )
        self.assertEqual(bhp["name"], "BHP GROUP LIMITED")
        self.assertEqual(bhp["exchange"], "ASX")
        self.assertEqual(cba["name"], "COMMONWEALTH BANK OF AUSTRALIA")
        self.assertEqual(cba["exchange"], "ASX")
        self.assertEqual(bhp["mapping_status"], "unmapped")

    def test_refresh_never_writes_information_items(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            database_path = Path(temporary_directory) / "web.sqlite3"
            cache_path = Path(temporary_directory) / "au_universe.json"
            repository = SQLiteInformationRepository(database_path)

            refresh_au_universe(
                path=cache_path,
                opener=directory_opener(),
            )

            self.assertEqual(repository.count(), 0)


if __name__ == "__main__":
    unittest.main()
