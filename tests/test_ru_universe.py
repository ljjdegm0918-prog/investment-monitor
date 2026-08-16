"""P5-0 Russia read-only universe tests."""

import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from investment_monitor.universe.ru_universe import (
    RuUniverseError,
    load_ru_universe,
    refresh_ru_universe,
    ru_universe_name_map,
    search_ru_universe,
)


class _FakeResponse:
    def __init__(self, payload):
        self._raw = json.dumps(payload).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def read(self):
        return self._raw


class _FakeOpener:
    def __init__(self, payload):
        self.payload = payload
        self.calls = 0

    def __call__(self, request, timeout=None):
        self.calls += 1
        return _FakeResponse(self.payload)


MOEX_PAYLOAD = {
    "securities": {
        "columns": ["SECID", "BOARDID", "SECNAME", "ISIN", "CURRENCYID",
                    "STATUS", "LATNAME"],
        "data": [
            ["SBER", "TQBR", "Sberbank", "RU0009029540", "RUB", "A",
             "Sberbank"],
            ["GAZP", "TQBR", "Gazprom", "RU0007661625", "RUB", "A",
             "Gazprom"],
            ["", "TQBR", "missing id", "RU0000000000", "RUB", "A", ""],
        ],
    }
}


class RuUniverseTests(unittest.TestCase):
    def test_refresh_is_official_readonly_unavailable(self):
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "ru.json"
            payload = refresh_ru_universe(
                path=path,
                opener=_FakeOpener(MOEX_PAYLOAD),
                refreshed_at="2026-08-16T00:00:00+00:00",
            )
        self.assertEqual(payload["source_tier"], "official")
        self.assertNotIn("trading_status", payload)
        self.assertTrue(payload["readonly"])
        self.assertTrue(payload["readonly"])
        self.assertEqual(payload["counts"]["tqbr"], 2)
        self.assertEqual(
            [item["ticker"] for item in payload["items"]], ["GAZP", "SBER"]
        )

    def test_name_map_and_search(self):
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "ru.json"
            refresh_ru_universe(
                path=path,
                opener=_FakeOpener(MOEX_PAYLOAD),
            )
            name_map = ru_universe_name_map(path)
            self.assertEqual(name_map["SBER"]["isin"], "RU0009029540")
            self.assertEqual(name_map["SBER"]["exchange"], "MOEX")
            hits = search_ru_universe("Gazprom", path)
            self.assertEqual(hits[0]["ticker"], "GAZP")

    def test_load_missing_cache_is_none(self):
        with TemporaryDirectory() as tmp:
            self.assertIsNone(load_ru_universe(Path(tmp) / "none.json"))

    def test_failure_raises(self):
        class BrokenOpener:
            def __call__(self, request, timeout=None):
                raise ConnectionError("boom")

        with TemporaryDirectory() as tmp:
            with self.assertRaises(RuUniverseError):
                refresh_ru_universe(
                    path=Path(tmp) / "ru.json",
                    opener=BrokenOpener(),
                )


if __name__ == "__main__":
    unittest.main()
