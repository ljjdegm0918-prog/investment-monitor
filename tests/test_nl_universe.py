from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from urllib.parse import urlsplit

from investment_monitor import (
    NlUniverseError,
    SQLiteInformationRepository,
    WebRepository,
    nl_universe_name_map,
    load_nl_universe,
    refresh_nl_universe,
    search_nl_universe,
)


FIXTURES = Path(__file__).parent / "fixtures" / "nl_universe"


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
                FIXTURES / "euronext_nl_sample.csv"
            ).read_bytes()
        },
        **kwargs,
    )


class NlUniverseRefreshTests(unittest.TestCase):
    def test_refresh_writes_cache_with_counts_and_name_map(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            cache_path = Path(temporary_directory) / "nl_universe.json"

            payload = refresh_nl_universe(
                path=cache_path,
                opener=directory_opener(),
                refreshed_at="2026-08-10T00:00:00+00:00",
            )
            loaded = load_nl_universe(cache_path)
            name_map = nl_universe_name_map(cache_path)
            by_ticker = search_nl_universe("ASML", cache_path)
            by_isin = search_nl_universe("NL0011794037", cache_path)

        self.assertEqual(payload["source"], ["euronext_live_csv"])
        self.assertEqual(
            payload["counts"],
            {
                "Euronext Amsterdam": 3,
                "Euronext Amsterdam, Brussels": 1,
            },
        )
        self.assertEqual(loaded, payload)
        self.assertEqual(
            name_map["ASML"],
            {
                "name": "ASML HOLDING",
                "exchange": "Euronext Amsterdam",
                "board": "Euronext Amsterdam",
                "isin": "NL0010273215",
            },
        )
        self.assertEqual(name_map["AD"]["exchange"], "Euronext Amsterdam, Brussels")
        self.assertEqual(by_ticker[0]["ticker"], "ASML")
        self.assertEqual(by_isin[0]["ticker"], "AD")

    def test_all_sources_fail_raises(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            cache_path = Path(temporary_directory) / "nl_universe.json"

            with self.assertRaises(NlUniverseError):
                refresh_nl_universe(
                    path=cache_path,
                    opener=directory_opener(
                        error_paths=("/en/pd_es/data/stocks/download",)
                    ),
                )

    def test_load_and_name_map_degrade_without_cache(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            cache_path = Path(temporary_directory) / "missing.json"

            self.assertIsNone(load_nl_universe(cache_path))
            self.assertEqual(nl_universe_name_map(cache_path), {})
            self.assertEqual(search_nl_universe("ASML", cache_path), [])

    def test_add_companies_batch_uses_nl_universe_name_fallback(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            database_path = Path(temporary_directory) / "web.sqlite3"
            cache_path = Path(temporary_directory) / "nl_universe.json"
            SQLiteInformationRepository(database_path)
            repository = WebRepository(database_path)
            refresh_nl_universe(
                path=cache_path,
                opener=directory_opener(),
            )

            result = repository.add_companies_batch(
                "ASML.AS, INGA",
                ("holdings",),
                None,
                market="nl",
                name_fallback=nl_universe_name_map(cache_path),
            )

        self.assertEqual(len(result["added"]), 2)
        asml = next(
            item for item in result["added"] if item["ticker"] == "ASML"
        )
        inga = next(
            item for item in result["added"] if item["ticker"] == "INGA"
        )
        self.assertEqual(asml["name"], "ASML HOLDING")
        self.assertEqual(asml["exchange"], "Euronext Amsterdam")
        self.assertEqual(inga["name"], "ING GROEP")
        self.assertEqual(asml["mapping_status"], "unmapped")

    def test_refresh_never_writes_information_items(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            database_path = Path(temporary_directory) / "web.sqlite3"
            cache_path = Path(temporary_directory) / "nl_universe.json"
            repository = SQLiteInformationRepository(database_path)

            refresh_nl_universe(
                path=cache_path,
                opener=directory_opener(),
            )

            self.assertEqual(repository.count(), 0)


if __name__ == "__main__":
    unittest.main()
