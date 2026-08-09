from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from urllib.parse import urlsplit

from investment_monitor import (
    CaUniverseError,
    SQLiteInformationRepository,
    WebRepository,
    ca_universe_name_map,
    load_ca_universe,
    refresh_ca_universe,
    search_ca_universe,
)


FIXTURES = Path(__file__).parent / "fixtures" / "ca_universe"


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


def tsx_opener(**kwargs):
    return FakeOpener(
        {
            "/json/company-directory/search/tsx/^": (
                FIXTURES / "tsx.json"
            ).read_bytes()
        },
        **kwargs,
    )


def tsxv_opener(**kwargs):
    return FakeOpener(
        {
            "/json/company-directory/search/tsxv/^": (
                FIXTURES / "tsxv.json"
            ).read_bytes()
        },
        **kwargs,
    )


class CaUniverseRefreshTests(unittest.TestCase):
    def test_refresh_writes_cache_with_counts_and_name_map(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            cache_path = Path(temporary_directory) / "ca_universe.json"

            payload = refresh_ca_universe(
                path=cache_path,
                tsx_opener=tsx_opener(),
                tsxv_opener=tsxv_opener(),
                refreshed_at="2026-08-08T00:00:00+00:00",
            )
            loaded = load_ca_universe(cache_path)
            name_map = ca_universe_name_map(cache_path)
            by_ticker = search_ca_universe("SHOP", cache_path)
            by_name = search_ca_universe("1911 Gold", cache_path)

        self.assertEqual(
            payload["source"],
            ["tsx_directory", "tsxv_directory"],
        )
        self.assertEqual(
            payload["counts"],
            {"TSX": 4, "TSXV": 3},
        )
        self.assertEqual(loaded, payload)
        self.assertEqual(
            name_map["RY"],
            {
                "name": "Royal Bank of Canada",
                "exchange": "TSX",
                "board": "TSX",
            },
        )
        self.assertEqual(name_map["SHOP"]["exchange"], "TSX")
        self.assertEqual(name_map["SHOP"]["board"], "TSX")
        self.assertEqual(name_map["SHOP.WT"]["exchange"], "TSX")
        self.assertEqual(
            name_map["ONE"],
            {
                "name": "01 Quantum Inc.",
                "exchange": "TSXV",
                "board": "TSXV",
            },
        )
        self.assertEqual(by_ticker[0]["ticker"], "SHOP")
        self.assertEqual(by_name[0]["ticker"], "AUMB")

    def test_duplicate_symbol_prefers_tsx_board(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            cache_path = Path(temporary_directory) / "ca_universe.json"

            payload = refresh_ca_universe(
                path=cache_path,
                tsx_opener=tsx_opener(),
                tsxv_opener=tsxv_opener(),
                refreshed_at="2026-08-08T00:00:00+00:00",
            )
            name_map = ca_universe_name_map(cache_path)

        self.assertEqual(name_map["RY"]["exchange"], "TSX")
        self.assertEqual(payload["counts"]["TSXV"], 3)

    def test_partial_failure_keeps_successful_board(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            cache_path = Path(temporary_directory) / "ca_universe.json"

            payload = refresh_ca_universe(
                path=cache_path,
                tsx_opener=tsx_opener(),
                tsxv_opener=tsxv_opener(
                    error_paths=("/json/company-directory/search/tsxv/^",)
                ),
                refreshed_at="2026-08-08T00:00:00+00:00",
            )

        self.assertEqual(payload["counts"]["TSX"], 4)
        self.assertEqual(payload["counts"]["TSXV"], 0)
        self.assertEqual(payload["source"], ["tsx_directory"])

    def test_all_sources_fail_raises(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            cache_path = Path(temporary_directory) / "ca_universe.json"

            with self.assertRaises(CaUniverseError):
                refresh_ca_universe(
                    path=cache_path,
                    tsx_opener=tsx_opener(
                        error_paths=("/json/company-directory/search/tsx/^",)
                    ),
                    tsxv_opener=tsxv_opener(
                        error_paths=("/json/company-directory/search/tsxv/^",)
                    ),
                )

    def test_load_and_name_map_degrade_without_cache(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            cache_path = Path(temporary_directory) / "missing.json"

            self.assertIsNone(load_ca_universe(cache_path))
            self.assertEqual(ca_universe_name_map(cache_path), {})
            self.assertEqual(search_ca_universe("SHOP", cache_path), [])

    def test_add_companies_batch_uses_ca_universe_name_fallback(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            database_path = Path(temporary_directory) / "web.sqlite3"
            cache_path = Path(temporary_directory) / "ca_universe.json"
            SQLiteInformationRepository(database_path)
            repository = WebRepository(database_path)
            refresh_ca_universe(
                path=cache_path,
                tsx_opener=tsx_opener(),
                tsxv_opener=tsxv_opener(),
            )

            result = repository.add_companies_batch(
                "RY.TO, AUMB.V",
                ("holdings",),
                None,
                market="ca",
                name_fallback=ca_universe_name_map(cache_path),
            )

        self.assertEqual(len(result["added"]), 2)
        royal = next(
            item for item in result["added"] if item["ticker"] == "RY"
        )
        aumb = next(
            item for item in result["added"] if item["ticker"] == "AUMB"
        )
        self.assertEqual(royal["name"], "Royal Bank of Canada")
        self.assertEqual(royal["exchange"], "TSX")
        self.assertEqual(aumb["name"], "1911 Gold Corporation")
        self.assertEqual(aumb["exchange"], "TSXV")
        self.assertEqual(royal["mapping_status"], "unmapped")

    def test_refresh_never_writes_information_items(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            database_path = Path(temporary_directory) / "web.sqlite3"
            cache_path = Path(temporary_directory) / "ca_universe.json"
            repository = SQLiteInformationRepository(database_path)

            refresh_ca_universe(
                path=cache_path,
                tsx_opener=tsx_opener(),
                tsxv_opener=tsxv_opener(),
            )

            self.assertEqual(repository.count(), 0)


if __name__ == "__main__":
    unittest.main()
