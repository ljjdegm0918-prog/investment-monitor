import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from urllib.parse import urlsplit

from investment_monitor import (
    SQLiteInformationRepository,
    TwUniverseError,
    WebRepository,
    load_tw_universe,
    refresh_tw_universe,
    search_tw_universe,
    tw_universe_name_map,
)


FIXTURES = Path(__file__).parent / "fixtures" / "tw_universe"


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


def twse_opener(**kwargs):
    return FakeOpener(
        {
            "/v1/opendata/t187ap03_L": (
                FIXTURES / "twse_t187ap03_L.json"
            ).read_bytes()
        },
        **kwargs,
    )


def tpex_opener(**kwargs):
    return FakeOpener(
        {
            "/openapi/v1/mopsfin_t187ap03_O": (
                FIXTURES / "tpex_t187ap03_O.json"
            ).read_bytes()
        },
        **kwargs,
    )


class TwUniverseRefreshTests(unittest.TestCase):
    def test_refresh_writes_cache_with_counts_and_name_map(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            cache_path = Path(temporary_directory) / "tw_universe.json"

            payload = refresh_tw_universe(
                path=cache_path,
                twse_opener=twse_opener(),
                tpex_opener=tpex_opener(),
                refreshed_at="2026-08-07T00:00:00+00:00",
            )
            loaded = load_tw_universe(cache_path)
            name_map = tw_universe_name_map(cache_path)
            by_ticker = search_tw_universe("2330", cache_path)
            by_name = search_tw_universe("茂生", cache_path)

        self.assertEqual(payload["source"], ["tpex_openapi", "twse_openapi"])
        self.assertEqual(
            payload["counts"],
            {"TWSE": 2, "TPEx": 2, "ESB": 0},
        )
        self.assertEqual(loaded, payload)
        self.assertEqual(
            name_map["2330"],
            {
                "name": "台灣積體電路製造股份有限公司",
                "exchange": "TWSE",
                "name_zh": "台灣積體電路製造股份有限公司",
                "name_en": "TSMC",
                "short_name": "台積電",
            },
        )
        self.assertEqual(
            name_map["1240"],
            {
                "name": "茂生農經股份有限公司",
                "exchange": "TPEx",
                "name_zh": "茂生農經股份有限公司",
                "name_en": "1240",
                "short_name": "茂生農經",
            },
        )
        self.assertEqual(by_ticker[0]["ticker"], "2330")
        self.assertEqual(by_name[0]["ticker"], "1240")

    def test_partial_failure_keeps_successful_board(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            cache_path = Path(temporary_directory) / "tw_universe.json"

            payload = refresh_tw_universe(
                path=cache_path,
                twse_opener=twse_opener(),
                tpex_opener=tpex_opener(
                    error_paths=("/openapi/v1/mopsfin_t187ap03_O",)
                ),
                refreshed_at="2026-08-07T00:00:00+00:00",
            )

        self.assertEqual(payload["counts"]["TWSE"], 2)
        self.assertEqual(payload["counts"]["TPEx"], 0)
        self.assertEqual(payload["source"], ["twse_openapi"])

    def test_all_sources_fail_raises(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            cache_path = Path(temporary_directory) / "tw_universe.json"

            with self.assertRaises(TwUniverseError):
                refresh_tw_universe(
                    path=cache_path,
                    twse_opener=twse_opener(
                        error_paths=("/v1/opendata/t187ap03_L",)
                    ),
                    tpex_opener=tpex_opener(
                        error_paths=("/openapi/v1/mopsfin_t187ap03_O",)
                    ),
                )

    def test_emerging_board_via_configured_url(self) -> None:
        emerging_path = "/openapi/v1/tpex_emerging"
        emerging_opener = FakeOpener(
            {
                emerging_path: (
                    FIXTURES / "tpex_emerging.json"
                ).read_bytes()
            }
        )
        with TemporaryDirectory() as temporary_directory:
            cache_path = Path(temporary_directory) / "tw_universe.json"

            payload = refresh_tw_universe(
                path=cache_path,
                twse_opener=twse_opener(),
                tpex_opener=tpex_opener(),
                emerging_opener=emerging_opener,
                emerging_url="https://example.test" + emerging_path,
                refreshed_at="2026-08-07T00:00:00+00:00",
            )
            name_map = tw_universe_name_map(cache_path)

        self.assertEqual(payload["counts"]["ESB"], 1)
        self.assertEqual(name_map["1781"]["exchange"], "ESB")
        self.assertEqual(name_map["1781"]["name"], "合世生醫科技股份有限公司")

    def test_load_and_name_map_degrade_without_cache(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            cache_path = Path(temporary_directory) / "missing.json"

            self.assertIsNone(load_tw_universe(cache_path))
            self.assertEqual(tw_universe_name_map(cache_path), {})
            self.assertEqual(search_tw_universe("2330", cache_path), [])

    def test_add_companies_batch_uses_tw_universe_name_fallback(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            database_path = Path(temporary_directory) / "web.sqlite3"
            cache_path = Path(temporary_directory) / "tw_universe.json"
            SQLiteInformationRepository(database_path)
            repository = WebRepository(database_path)
            refresh_tw_universe(
                path=cache_path,
                twse_opener=twse_opener(),
                tpex_opener=tpex_opener(),
            )

            result = repository.add_companies_batch(
                "2330",
                ("holdings",),
                None,
                market="tw",
                name_fallback=tw_universe_name_map(cache_path),
            )

        self.assertEqual(len(result["added"]), 1)
        added = result["added"][0]
        self.assertEqual(added["name"], "台灣積體電路製造股份有限公司")
        self.assertEqual(added["exchange"], "TWSE")
        self.assertEqual(added["market"], "tw")
        self.assertEqual(added["mapping_status"], "unmapped")


if __name__ == "__main__":
    unittest.main()
