"""Z1 US universe tests (offline fake opener)."""

import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from investment_monitor.us_universe import (
    UsUniverseError,
    load_us_universe,
    refresh_us_universe,
    search_us_universe,
    us_universe_name_map,
)


class _FakeResponse:
    def __init__(self, payload):
        self._raw = json.dumps(payload).encode("utf-8")
        self.headers = {}

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def read(self):
        return self._raw


class _FakeOpener:
    def __init__(self, payload):
        self.payload = payload
        self.request = None

    def __call__(self, request, timeout=None):
        self.request = request
        return _FakeResponse(self.payload)


class UsUniverseTests(unittest.TestCase):
    def test_refresh_parses_sec_ticker_exchange_rows(self):
        payload = {
            "fields": ["cik", "name", "ticker", "exchange"],
            "data": [
                [320193, "Apple Inc.", "AAPL", "Nasdaq"],
                [789019, "MICROSOFT CORP", "MSFT", "Nasdaq"],
            ],
        }
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "us.json"
            result = refresh_us_universe(
                path=path, opener=_FakeOpener(payload),
                refreshed_at="2026-08-16T00:00:00+00:00",
            )
        self.assertEqual(result["source_tier"], "official")
        self.assertEqual(result["counts"]["companies"], 2)
        self.assertEqual(
            {item["ticker"] for item in result["items"]}, {"AAPL", "MSFT"}
        )

    def test_name_map_and_search(self):
        payload = {
            "fields": ["cik", "name", "ticker", "exchange"],
            "data": [[320193, "Apple Inc.", "AAPL", "Nasdaq"]],
        }
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "us.json"
            refresh_us_universe(path=path, opener=_FakeOpener(payload))
            name_map = us_universe_name_map(path)
            self.assertEqual(name_map["AAPL"]["exchange"], "Nasdaq")
            self.assertEqual(name_map["AAPL"]["cik"], "320193")
            hits = search_us_universe("Apple", path)
            self.assertEqual(hits[0]["ticker"], "AAPL")

    def test_failure_raises(self):
        class BrokenOpener:
            def __call__(self, request, timeout=None):
                raise ConnectionError("boom")

        with TemporaryDirectory() as tmp:
            with self.assertRaises(UsUniverseError):
                refresh_us_universe(
                    path=Path(tmp) / "us.json", opener=BrokenOpener()
                )

    def test_missing_cache_is_none(self):
        with TemporaryDirectory() as tmp:
            self.assertIsNone(load_us_universe(Path(tmp) / "nope.json"))


if __name__ == "__main__":
    unittest.main()
