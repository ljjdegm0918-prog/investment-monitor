from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from urllib.parse import urlsplit

from investment_monitor.universe.de_universe import (
    DeUniverseError,
    de_universe_name_map,
    load_de_universe,
    refresh_de_universe,
    search_de_universe,
)

FIXTURES = Path(__file__).parent / "fixtures" / "de_universe"


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
        for key, body in self.fixtures.items():
            if path.endswith(key) or key in path:
                return FakeResponse(body)
        raise AssertionError(f"unexpected url: {request.full_url}")


class DeUniverseTests(unittest.TestCase):
    def test_refresh_keeps_cs_only_and_builds_name_map(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            cache_path = Path(temporary_directory) / "de_universe.json"
            opener = FakeOpener(
                {
                    "t7-xetr-allTradableInstruments.csv": (
                        FIXTURES / "xetra_de_sample.csv"
                    ).read_bytes()
                }
            )
            payload = refresh_de_universe(
                path=cache_path,
                opener=opener,
                refreshed_at="2026-08-10T00:00:00+00:00",
            )
            loaded = load_de_universe(cache_path)
            name_map = de_universe_name_map(cache_path)
            hits = search_de_universe("SAP", cache_path)

        self.assertEqual(payload["source"], ["xetra_all_tradable_csv"])
        self.assertEqual(payload["counts"], {"DAX": 2})
        self.assertEqual(loaded["counts"], {"DAX": 2})
        self.assertEqual(name_map["SAP"]["isin"], "DE0007164600")
        self.assertEqual(name_map["SIE"]["board"], "DAX")
        self.assertNotIn("ETF1", name_map)
        self.assertNotIn("SKIP", name_map)
        self.assertEqual(hits[0]["ticker"], "SAP")

    def test_refresh_failure_raises(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            cache_path = Path(temporary_directory) / "de_universe.json"
            opener = FakeOpener(
                {"t7-xetr-allTradableInstruments.csv": b""},
                error_paths={
                    "/resource/blob/1528/a31c10e3183f4c5dd721f9c7f9eaaaea/data/"
                    "t7-xetr-allTradableInstruments.csv"
                },
            )
            with self.assertRaises(DeUniverseError):
                refresh_de_universe(path=cache_path, opener=opener)


if __name__ == "__main__":
    unittest.main()
