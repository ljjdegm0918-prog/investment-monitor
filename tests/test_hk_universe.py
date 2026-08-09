import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from investment_monitor import (
    HkUniverseError,
    SQLiteInformationRepository,
    WebRepository,
    hk_universe_name_map,
    load_hk_universe,
    refresh_hk_universe,
)


def row(code: str, stock_id: str, name: str) -> dict:
    return {
        "stock_code": code,
        "stock_id": stock_id,
        "stock_name": name,
    }


class FakeClient:
    def __init__(self, failure=None) -> None:
        self.failure = failure
        self.calls: list = []
        self.active_e = [
            row("00700", "15157", "TENCENT"),
            row("00001", "3749", "CKH HOLDINGS"),
        ]
        self.active_c = [row("00700", "15157", "騰訊控股")]
        self.inactive_e = [row("00010", "3756", "HANG SENG BANK")]
        self.inactive_c = [row("00010", "3756", "恒生銀行")]

    def fetch_stock_list(self, status: str, lang: str) -> list:
        self.calls.append((status, lang))
        if self.failure is not None:
            raise self.failure
        return list(getattr(self, f"{status}_{lang}"))


class HkUniverseRefreshTests(unittest.TestCase):
    def test_refresh_writes_cache_with_active_names_and_counts(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            cache_path = Path(temporary_directory) / "hk_universe.json"
            client = FakeClient()

            payload = refresh_hk_universe(
                path=cache_path,
                client=client,
                refreshed_at="2026-08-06T00:00:00+00:00",
            )
            loaded = load_hk_universe(cache_path)
            name_map = hk_universe_name_map(cache_path)

        self.assertEqual(payload["source"], "hkexnews_activestock")
        self.assertEqual(payload["refreshed_at"], "2026-08-06T00:00:00+00:00")
        self.assertEqual(payload["counts"], {"active": 2, "inactive": 1})
        self.assertEqual(
            payload["entries"]["00700"],
            {
                "ticker": "00700",
                "stock_id": "15157",
                "name": "TENCENT",
                "name_zh": "騰訊控股",
                "exchange": "SEHK",
                "status": "active",
            },
        )
        self.assertEqual(payload["entries"]["00010"]["status"], "inactive")
        self.assertEqual(loaded, payload)
        self.assertEqual(name_map["00700"]["name"], "TENCENT")
        self.assertEqual(name_map["00700"]["exchange"], "SEHK")
        self.assertEqual(name_map["00700"]["name_zh"], "騰訊控股")
        self.assertEqual(name_map["00010"]["status"], "inactive")

    def test_refresh_can_exclude_inactive_entries(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            cache_path = Path(temporary_directory) / "hk_universe.json"

            payload = refresh_hk_universe(
                path=cache_path,
                client=FakeClient(),
                include_inactive=False,
                refreshed_at="2026-08-06T00:00:00+00:00",
            )

        self.assertNotIn("00010", payload["entries"])
        self.assertEqual(payload["counts"]["inactive"], 0)

    def test_refresh_client_failure_raises_hk_universe_error(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            cache_path = Path(temporary_directory) / "hk_universe.json"
            client = FakeClient(failure=RuntimeError("boom"))

            with self.assertRaisesRegex(HkUniverseError, "boom"):
                refresh_hk_universe(path=cache_path, client=client)

    def test_load_and_name_map_degrade_without_cache(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            cache_path = Path(temporary_directory) / "missing.json"

            self.assertIsNone(load_hk_universe(cache_path))
            self.assertEqual(hk_universe_name_map(cache_path), {})

    def test_name_map_prefers_active_over_inactive(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            cache_path = Path(temporary_directory) / "hk_universe.json"
            payload = {
                "source": "hkexnews_activestock",
                "refreshed_at": "2026-08-06T00:00:00+00:00",
                "entries": {
                    "00700": {
                        "ticker": "00700",
                        "stock_id": "15157",
                        "name": "TENCENT",
                        "name_zh": "騰訊控股",
                        "exchange": "SEHK",
                        "status": "active",
                    },
                    "00010": {
                        "ticker": "00010",
                        "stock_id": "3756",
                        "name": "HANG SENG BANK",
                        "name_zh": "恒生銀行",
                        "exchange": "SEHK",
                        "status": "inactive",
                    },
                },
            }
            cache_path.write_text(
                json.dumps(payload),
                encoding="utf-8",
            )

            name_map = hk_universe_name_map(cache_path)

        self.assertEqual(name_map["00700"]["status"], "active")
        self.assertEqual(name_map["00010"]["status"], "inactive")

    def test_add_companies_batch_uses_hk_universe_name_fallback(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            database_path = Path(temporary_directory) / "web.sqlite3"
            cache_path = Path(temporary_directory) / "hk_universe.json"
            SQLiteInformationRepository(database_path)
            repository = WebRepository(database_path)
            refresh_hk_universe(path=cache_path, client=FakeClient())

            result = repository.add_companies_batch(
                "00700",
                ("holdings",),
                None,
                market="hk",
                name_fallback=hk_universe_name_map(cache_path),
            )

        self.assertEqual(len(result["added"]), 1)
        added = result["added"][0]
        self.assertEqual(added["name"], "TENCENT")
        self.assertEqual(added["exchange"], "SEHK")
        self.assertEqual(added["market"], "hk")
        self.assertEqual(added["mapping_status"], "unmapped")


if __name__ == "__main__":
    unittest.main()
