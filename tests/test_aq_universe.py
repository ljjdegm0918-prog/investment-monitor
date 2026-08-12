"""Tests for the Aquis (AQSE) tradeable universe cache (market=aq, AQ-2).

AQ-2 spike (2026-08-10): the official Aquis directory
(``embed.aquis.eu/companies`` and ``www.aquis.eu``) is behind a Vercel
bot challenge (HTTP 429, ``X-Vercel-Mitigated: challenge``) that blocks
stdlib/curl clients, and no key-free official JSON/CSV/XLS exists. The
wired refresh source is the ticker.app AQSE mirror page
(``https://www.ticker.app/aqse``), an unofficial partial directory
(~79 instruments live 2026-08-10; 61 with ISIN) which is honestly
labelled as such. The cache is breadth only and never flows into
information_items.
"""

from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from urllib.parse import urlsplit

from investment_monitor import (
    AqUniverseError,
    SQLiteInformationRepository,
    WebRepository,
    load_aq_universe,
    refresh_aq_universe,
    search_aq_universe,
    aq_universe_name_map,
)


FIXTURES = Path(__file__).parent / "fixtures" / "aq_universe"


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
    """Fake opener keyed by host/path for the ticker.app directory."""

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


def aq_opener(**kwargs):
    return HostAwareFakeOpener(
        {
            ("www.ticker.app", "/aqse"): (
                FIXTURES / "ticker_app_aqse.html"
            ).read_bytes(),
        },
        **kwargs,
    )


class AqUniverseRefreshTests(unittest.TestCase):
    def test_refresh_writes_cache_with_counts_and_name_map(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            cache_path = Path(temporary_directory) / "aq_universe.json"

            payload = refresh_aq_universe(
                path=cache_path,
                opener=aq_opener(),
                refreshed_at="2026-08-10T00:00:00+00:00",
            )
            loaded = load_aq_universe(cache_path)
            name_map = aq_universe_name_map(cache_path)
            by_ticker = search_aq_universe("ADB", cache_path)
            by_isin = search_aq_universe("GB00BF01VL55", cache_path)
            by_name = search_aq_universe("Ace Liberty", cache_path)

        self.assertEqual(payload["source"], ["ticker_app_aqse_html"])
        self.assertEqual(payload["counts"], {"AQSE": 5})
        # The duplicated directory table and the badge-less widget rows
        # must not inflate the count.
        self.assertEqual(loaded, payload)
        self.assertEqual(
            name_map["ALSP"],
            {
                "name": "Ace Liberty & Stone plc",
                "exchange": "AQSE",
                "board": "AQSE",
                "isin": "GB00BF01VL55",
            },
        )
        self.assertEqual(name_map["SVEN"]["name"], "S-Ventures Plc")
        self.assertEqual(name_map["SVEN"]["isin"], "")
        self.assertEqual(name_map["ETHL"]["isin"], "SGXZ84721265")
        self.assertEqual(by_ticker[0]["ticker"], "ADB")
        self.assertEqual(by_isin[0]["ticker"], "ALSP")
        self.assertEqual(by_name[0]["ticker"], "ALSP")

    def test_refresh_raises_when_the_mirror_is_unreachable(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            cache_path = Path(temporary_directory) / "aq_universe.json"

            with self.assertRaises(AqUniverseError):
                refresh_aq_universe(
                    path=cache_path,
                    opener=aq_opener(
                        error_paths=(("www.ticker.app", "/aqse"),)
                    ),
                )

    def test_load_and_name_map_degrade_without_cache(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            cache_path = Path(temporary_directory) / "missing.json"

            self.assertIsNone(load_aq_universe(cache_path))
            self.assertEqual(aq_universe_name_map(cache_path), {})
            self.assertEqual(search_aq_universe("ADB", cache_path), [])

    def test_add_companies_batch_uses_aq_universe_name_fallback(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            database_path = Path(temporary_directory) / "web.sqlite3"
            cache_path = Path(temporary_directory) / "aq_universe.json"
            SQLiteInformationRepository(database_path)
            repository = WebRepository(database_path)
            refresh_aq_universe(
                path=cache_path,
                opener=aq_opener(),
            )

            result = repository.add_companies_batch(
                "ADB.AQ, ALSP",
                ("holdings",),
                None,
                market="aq",
                name_fallback=aq_universe_name_map(cache_path),
            )

        self.assertEqual(len(result["added"]), 2)
        adb = next(
            item for item in result["added"] if item["ticker"] == "ADB"
        )
        alsp = next(
            item for item in result["added"] if item["ticker"] == "ALSP"
        )
        self.assertEqual(adb["name"], "Adnams plc")
        self.assertEqual(adb["exchange"], "AQSE")
        self.assertEqual(alsp["name"], "Ace Liberty & Stone plc")
        self.assertEqual(alsp["exchange"], "AQSE")
        self.assertEqual(adb["mapping_status"], "unmapped")

    def test_refresh_never_writes_information_items(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            database_path = Path(temporary_directory) / "web.sqlite3"
            cache_path = Path(temporary_directory) / "aq_universe.json"
            repository = SQLiteInformationRepository(database_path)

            refresh_aq_universe(
                path=cache_path,
                opener=aq_opener(),
            )

            self.assertEqual(repository.count(), 0)


if __name__ == "__main__":
    unittest.main()
