"""Tests for the Eurex product universe cache (market=eux, EUX-2).

EUX-2 spike (2026-08-11): the official Eurex product list CSV (linked
from ``eurex.com/ex-en/markets/productSearch``) is key-free and
server-side, product-level (no individual expiry contracts), with
PRODUCT_ID / PRODUCT_TYPE / PRODUCT_NAME / PRODUCT_GROUP / PRODUCT_ISIN
etc. This is a derivatives directory - no Xetra cash equities/ETFs and no
Cboe Europe symbols are mixed in.
"""

from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from urllib.parse import urlsplit

from investment_monitor import (
    EuxUniverseError,
    SQLiteInformationRepository,
    WebRepository,
    load_eux_universe,
    refresh_eux_universe,
    search_eux_universe,
    eux_universe_name_map,
)


FIXTURES = Path(__file__).parent / "fixtures" / "eux_universe"


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
        for error_path in self.error_paths:
            if error_path in path:
                raise OSError(f"blocked {path}")
        for key, body in self.fixtures.items():
            if key in path:
                return FakeResponse(body)
        raise AssertionError(f"unexpected url: {request.full_url}")


def eux_opener(**kwargs):
    return FakeOpener(
        {
            "productlist.csv": (FIXTURES / "productlist.csv").read_bytes(),
        },
        **kwargs,
    )


class EuxUniverseRefreshTests(unittest.TestCase):
    def test_refresh_writes_cache_with_counts_and_name_map(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            cache_path = Path(temporary_directory) / "eux_universe.json"

            payload = refresh_eux_universe(
                path=cache_path,
                opener=eux_opener(),
                refreshed_at="2026-08-11T00:00:00+00:00",
            )
            loaded = load_eux_universe(cache_path)
            name_map = eux_universe_name_map(cache_path)
            by_code = search_eux_universe("FDAX", cache_path)
            by_group = search_eux_universe("INDEX FUTURES", cache_path)
            by_isin = search_eux_universe("DE0009652644", cache_path)

        self.assertEqual(payload["source"], ["eurex_productlist_csv"])
        self.assertEqual(
            payload["counts"],
            {"FBND": 1, "FINX": 2, "FSTK": 1, "OSTK": 1},
        )
        self.assertEqual(
            payload["counts_by_group"],
            {
                "FIXED INCOME FUTURES": 1,
                "INDEX FUTURES": 2,
                "SINGLE STOCK FUTURES": 1,
                "SINGLE STOCK OPTIONS": 1,
            },
        )
        self.assertEqual(loaded, payload)
        self.assertEqual(
            name_map["FDAX"],
            {
                "name": "DAX Futures",
                "exchange": "Eurex",
                "board": "Eurex",
                "isin": "DE0009652644",
                "product_type": "FINX",
                "group": "INDEX FUTURES",
            },
        )
        self.assertEqual(name_map["2FE"]["group"], "SINGLE STOCK OPTIONS")
        self.assertEqual(by_code[0]["ticker"], "FDAX")
        self.assertEqual(
            {item["ticker"] for item in by_group},
            {"FDAX", "ESX5"},
        )
        self.assertEqual(by_isin[0]["ticker"], "FDAX")

    def test_refresh_raises_when_the_csv_is_unreachable(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            cache_path = Path(temporary_directory) / "eux_universe.json"

            with self.assertRaises(EuxUniverseError):
                refresh_eux_universe(
                    path=cache_path,
                    opener=eux_opener(
                        error_paths=("/data/productlist.csv",)
                    ),
                )

    def test_load_and_name_map_degrade_without_cache(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            cache_path = Path(temporary_directory) / "missing.json"

            self.assertIsNone(load_eux_universe(cache_path))
            self.assertEqual(eux_universe_name_map(cache_path), {})
            self.assertEqual(search_eux_universe("FDAX", cache_path), [])

    def test_add_companies_batch_uses_eux_universe_name_fallback(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            database_path = Path(temporary_directory) / "web.sqlite3"
            cache_path = Path(temporary_directory) / "eux_universe.json"
            SQLiteInformationRepository(database_path)
            repository = WebRepository(database_path)
            refresh_eux_universe(
                path=cache_path,
                opener=eux_opener(),
            )

            result = repository.add_companies_batch(
                "FDAX.EUX, 2FE",
                ("holdings",),
                None,
                market="eux",
                name_fallback=eux_universe_name_map(cache_path),
            )

        self.assertEqual(len(result["added"]), 2)
        fdax = next(
            item for item in result["added"] if item["ticker"] == "FDAX"
        )
        fe = next(
            item for item in result["added"] if item["ticker"] == "2FE"
        )
        self.assertEqual(fdax["name"], "DAX Futures")
        self.assertEqual(fdax["exchange"], "Eurex")
        self.assertEqual(fe["name"], "Ferrari")
        self.assertEqual(fdax["mapping_status"], "unmapped")

    def test_refresh_never_writes_information_items(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            database_path = Path(temporary_directory) / "web.sqlite3"
            cache_path = Path(temporary_directory) / "eux_universe.json"
            repository = SQLiteInformationRepository(database_path)

            refresh_eux_universe(
                path=cache_path,
                opener=eux_opener(),
            )

            self.assertEqual(repository.count(), 0)


if __name__ == "__main__":
    unittest.main()
