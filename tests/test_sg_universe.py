from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from investment_monitor import (
    SQLiteInformationRepository,
    SgUniverseError,
    WebRepository,
    load_sg_universe,
    refresh_sg_universe,
    search_sg_universe,
    sg_universe_name_map,
)


class _Response:
    def __init__(self, payload):
        import json
        self._body = json.dumps(payload).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return False

    def read(self):
        return self._body


class SgUniverseBoundaryTests(unittest.TestCase):
    def test_load_and_name_map_degrade_without_cache(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            cache_path = Path(temporary_directory) / "missing.json"

            self.assertIsNone(load_sg_universe(cache_path))
            self.assertEqual(sg_universe_name_map(cache_path), {})
            self.assertEqual(search_sg_universe("D05", cache_path), [])

    def test_load_accepts_manual_cache_shape(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            cache_path = Path(temporary_directory) / "sg_universe.json"
            cache_path.write_text(
                '{"updated_at":"2026-08-10T00:00:00+00:00",'
                '"source":["manual"],"counts":{"SGX Mainboard":1},'
                '"items":[{"ticker":"D05","name":"DBS Group Holdings",'
                '"isin":"SG1L01001701","board":"SGX Mainboard"}]}',
                encoding="utf-8",
            )

            payload = load_sg_universe(cache_path)
            name_map = sg_universe_name_map(cache_path)
            by_ticker = search_sg_universe("D05", cache_path)
            by_isin = search_sg_universe("SG1L01001701", cache_path)

        self.assertEqual(payload["counts"], {"SGX Mainboard": 1})
        self.assertEqual(
            name_map["D05"],
            {
                "name": "DBS Group Holdings",
                "exchange": "SGX Mainboard",
                "board": "SGX Mainboard",
                "isin": "SG1L01001701",
            },
        )
        self.assertEqual(by_ticker[0]["ticker"], "D05")
        self.assertEqual(by_isin[0]["ticker"], "D05")

    def test_refresh_builds_strict_partial_third_party_universe(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            cache_path = Path(temporary_directory) / "sg_universe.json"
            rows = [
                {
                    "ticker": f"S{i:03d}",
                    "company_name": f"Company {i}",
                    "board": "Mainboard",
                    "is_active": True,
                    "isin": f"SG{i:010d}",
                    "uen": f"UEN{i:08d}",
                    "lei": None,
                }
                for i in range(100)
            ]
            payload = refresh_sg_universe(
                path=cache_path,
                opener=lambda request, timeout: _Response(
                    {"data": rows, "meta": {"count": 100}}
                ),
                refreshed_at="2026-08-16T00:00:00+00:00",
            )

        self.assertEqual(len(payload["items"]), 100)
        self.assertEqual(payload["source_tier"], "third_party")
        self.assertEqual(payload["coverage"], "partial_not_official_sgx_master")

    def test_refresh_rejects_count_mismatch(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            with self.assertRaises(SgUniverseError):
                refresh_sg_universe(
                    path=Path(temporary_directory) / "sg.json",
                    opener=lambda request, timeout: _Response(
                        {"data": [], "meta": {"count": 1}}
                    ),
                )

    def test_add_companies_batch_without_universe_is_unmapped(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            database_path = Path(temporary_directory) / "web.sqlite3"
            SQLiteInformationRepository(database_path)
            repository = WebRepository(database_path)

            result = repository.add_companies_batch(
                "D05.SI",
                ("holdings",),
                None,
                market="sg",
                name_fallback=sg_universe_name_map(),
            )
            companies = repository.companies()

        self.assertEqual(len(result["added"]), 1)
        self.assertEqual(result["added"][0]["ticker"], "D05")
        self.assertEqual(result["added"][0]["mapping_status"], "unmapped")
        self.assertEqual(companies[0]["market"], "sg")

    def test_universe_never_writes_information_items(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            database_path = Path(temporary_directory) / "web.sqlite3"
            repository = SQLiteInformationRepository(database_path)

            self.assertEqual(repository.count(), 0)


if __name__ == "__main__":
    unittest.main()
