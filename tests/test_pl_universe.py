"""Tests for the Poland tradeable universe cache (market=pl, PL-2).

Mirrors ``test_be_universe.py`` / ``test_ch_universe.py``: refresh reads
the two key-free official GPW HTML directories (Main Market via
``www.gpw.pl/spolki`` and NewConnect via ``newconnect.pl/spolki``), keeps
rows with ISIN/ticker/name, and writes a breadth-only cache that never
flows into information_items. Partial source failure keeps the other
board; only when both sources fail is ``PlUniverseError`` raised.
"""

from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from urllib.parse import urlsplit

from investment_monitor import (
    PlUniverseError,
    SQLiteInformationRepository,
    WebRepository,
    load_pl_universe,
    pl_universe_name_map,
    refresh_pl_universe,
    search_pl_universe,
)


FIXTURES = Path(__file__).parent / "fixtures" / "pl_universe"


class FakeResponse:
    def __init__(self, payload: bytes) -> None:
        self._body = payload

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return None

    def read(self) -> bytes:
        return self._body


class HostAwareFakeOpener:
    """Fake opener keyed by (host, path) for the two PL directory hosts."""

    def __init__(self, fixtures: dict, error_paths=()) -> None:
        self.fixtures = fixtures
        self.error_paths = set(error_paths)
        self.calls: list = []

    def __call__(self, request, timeout=None):
        split = urlsplit(request.full_url)
        key = (split.hostname, split.path)
        self.calls.append(key)
        if key in self.error_paths:
            raise OSError(f"blocked {key}")
        if key in self.fixtures:
            return FakeResponse(self.fixtures[key])
        raise AssertionError(f"unexpected url: {request.full_url}")


def pl_opener(**kwargs):
    return HostAwareFakeOpener(
        {
            ("www.gpw.pl", "/spolki"): (
                FIXTURES / "gpw_main.html"
            ).read_bytes(),
            ("newconnect.pl", "/spolki"): (
                FIXTURES / "newconnect.html"
            ).read_bytes(),
        },
        **kwargs,
    )


class PlUniverseRefreshTests(unittest.TestCase):
    def test_refresh_writes_cache_with_counts_and_name_map(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            cache_path = Path(temporary_directory) / "pl_universe.json"

            payload = refresh_pl_universe(
                path=cache_path,
                opener=pl_opener(),
                refreshed_at="2026-08-10T00:00:00+00:00",
            )
            loaded = load_pl_universe(cache_path)
            name_map = pl_universe_name_map(cache_path)
            by_ticker = search_pl_universe("PKO", cache_path)
            by_isin = search_pl_universe("PLPKO0000016", cache_path)
            by_board = search_pl_universe("NewConnect", cache_path)

        self.assertEqual(
            payload["source"],
            ["gpw_spolki_html", "newconnect_spolki_html"],
        )
        self.assertEqual(
            payload["counts"],
            {"GPW Main Market": 3, "NewConnect": 2},
        )
        self.assertEqual(loaded, payload)
        self.assertEqual(
            name_map["PKO"],
            {
                "name": "POWSZECHNA KASA OSZCZEDNOSCI BANK POLSKI",
                "exchange": "GPW Main Market",
                "board": "GPW Main Market",
                "isin": "PLPKO0000016",
            },
        )
        self.assertEqual(
            name_map["4MB"]["exchange"],
            "NewConnect",
        )
        self.assertEqual(by_ticker[0]["ticker"], "PKO")
        self.assertEqual(by_isin[0]["ticker"], "PKO")
        self.assertEqual(
            {item["ticker"] for item in by_board},
            {"4MB", "ABK"},
        )

    def test_one_source_failure_keeps_the_other_board(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            cache_path = Path(temporary_directory) / "pl_universe.json"

            payload = refresh_pl_universe(
                path=cache_path,
                opener=pl_opener(
                    error_paths=(("newconnect.pl", "/spolki"),)
                ),
                refreshed_at="2026-08-10T00:00:00+00:00",
            )
            name_map = pl_universe_name_map(cache_path)

        self.assertEqual(payload["source"], ["gpw_spolki_html"])
        self.assertEqual(payload["counts"], {"GPW Main Market": 3})
        self.assertIn("PKO", name_map)
        self.assertNotIn("4MB", name_map)

    def test_all_sources_fail_raises(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            cache_path = Path(temporary_directory) / "pl_universe.json"

            with self.assertRaises(PlUniverseError):
                refresh_pl_universe(
                    path=cache_path,
                    opener=pl_opener(
                        error_paths=(
                            ("www.gpw.pl", "/spolki"),
                            ("newconnect.pl", "/spolki"),
                        )
                    ),
                )

    def test_load_and_name_map_degrade_without_cache(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            cache_path = Path(temporary_directory) / "missing.json"

            self.assertIsNone(load_pl_universe(cache_path))
            self.assertEqual(pl_universe_name_map(cache_path), {})
            self.assertEqual(search_pl_universe("PKO", cache_path), [])

    def test_add_companies_batch_uses_pl_universe_name_fallback(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            database_path = Path(temporary_directory) / "web.sqlite3"
            cache_path = Path(temporary_directory) / "pl_universe.json"
            SQLiteInformationRepository(database_path)
            repository = WebRepository(database_path)
            refresh_pl_universe(
                path=cache_path,
                opener=pl_opener(),
            )

            result = repository.add_companies_batch(
                "PKO.WA, 4MB",
                ("holdings",),
                None,
                market="pl",
                name_fallback=pl_universe_name_map(cache_path),
            )

        self.assertEqual(len(result["added"]), 2)
        pko = next(
            item for item in result["added"] if item["ticker"] == "PKO"
        )
        four_mb = next(
            item for item in result["added"] if item["ticker"] == "4MB"
        )
        self.assertEqual(pko["name"], "POWSZECHNA KASA OSZCZEDNOSCI BANK POLSKI")
        self.assertEqual(pko["exchange"], "GPW Main Market")
        self.assertEqual(four_mb["name"], "4MOBILITY SPÓŁKA AKCYJNA")
        self.assertEqual(four_mb["exchange"], "NewConnect")
        self.assertEqual(pko["mapping_status"], "unmapped")

    def test_refresh_never_writes_information_items(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            database_path = Path(temporary_directory) / "web.sqlite3"
            cache_path = Path(temporary_directory) / "pl_universe.json"
            repository = SQLiteInformationRepository(database_path)

            refresh_pl_universe(
                path=cache_path,
                opener=pl_opener(),
            )

            self.assertEqual(repository.count(), 0)


if __name__ == "__main__":
    unittest.main()
