"""Add-company 加速契约测试：慢回填时秒回 + 单任务多市场后台回填。

定义「添加公司加速」契约：
- POST /api/companies/batch 即使底层回填很慢，也必须在 2 秒内返回；
- 响应不再内联同步 collection，而是返回 collection=null + backfill_task_id + backfill_status=queued；
- 公司仍需真实落库；
- 一次请求（含 TICKER@MARKET 多市场）只建一个后台任务，GET /api/backfill-tasks/<id> 可查。
"""

import json
import time
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from investment_monitor.application import ConfiguredCollectionResult
from investment_monitor.repository import SaveResult
from investment_monitor.web import WebApplication

SLOW_BACKFILL_SECONDS = 4.0
TERMINAL_STATUSES = ("success", "partial", "failure")


class _NoneResolver:
    """A resolver that never maps a ticker (non-US markets stay unmapped)."""

    def resolve(self, ticker):
        return None


class AddCompanyAsyncTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = TemporaryDirectory()
        self.project_root = Path(self.temporary_directory.name)
        (self.project_root / "config").mkdir()
        (self.project_root / "data").mkdir()
        (self.project_root / "config" / "settings.yaml").write_text(
            "enabled_sources:\n  - sec\ndatabase_path: ../data/web.sqlite3\n",
            encoding="utf-8",
        )
        (self.project_root / "config" / "universe.csv").write_text(
            "ticker,list_type\nAAPL,holdings\n", encoding="utf-8"
        )
        cache_directory = self.project_root / ".cache" / "investment_monitor"
        cache_directory.mkdir(parents=True)
        (cache_directory / "company_tickers.json").write_text(
            json.dumps({
                "0": {"cik_str": 320193, "ticker": "AAPL", "title": "Apple Inc."},
            }),
            encoding="utf-8",
        )
        self.collection_calls = []
        self.application = WebApplication(
            self.project_root,
            collection_runner=self.slow_collection_runner,
        )

    def tearDown(self) -> None:
        self.temporary_directory.cleanup()

    def _build_result(self):
        """构造与 noop_collection_runner 同结构的空回填结果（不触碰 DB）。"""
        return ConfiguredCollectionResult(
            items=(),
            failures=(),
            save_result=SaveResult(),
            database_path=self.project_root / "data" / "web.sqlite3",
            stored_count=0,
        )

    def slow_collection_runner(self, **kwargs):
        """先睡 4 秒再返回空结果，模拟慢回填。"""
        self.collection_calls.append(kwargs)
        time.sleep(SLOW_BACKFILL_SECONDS)
        return self._build_result()

    def noop_collection_runner(self, **kwargs):
        """立即返回空结果。"""
        self.collection_calls.append(kwargs)
        return self._build_result()

    def payload(self, response):
        return json.loads(response.body.decode("utf-8"))

    def _create_list(self, application, name="Long Term"):
        created = self.payload(application.handle(
            "POST", "/api/lists", json.dumps({"name": name}).encode()
        ))
        return created["list"]["slug"]

    def _wait_for_backfill(self, application, task_id, timeout=5.0):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            task = self.payload(application.handle(
                "GET", f"/api/backfill-tasks/{task_id}"
            ))
            if task["status"] in TERMINAL_STATUSES:
                return task
            time.sleep(0.02)
        self.fail("backfill task did not reach a terminal state")

    def test_batch_add_returns_fast_with_queued_backfill_task(self) -> None:
        slug = self._create_list(self.application)
        started = time.monotonic()
        with patch.object(self.application, "hkexnews_resolver", _NoneResolver()):
            response = self.application.handle(
                "POST", "/api/companies/batch",
                json.dumps({"tickers": "00700@HK", "lists": [slug]}).encode(),
            )
        elapsed = time.monotonic() - started
        payload = self.payload(response)
        added_by_key = {
            (record["ticker"], record["market"]) for record in payload["added"]
        }

        self.assertEqual(response.status, 201)
        self.assertIn(("00700", "hk"), added_by_key)
        self.assertIsNone(payload.get("collection"))
        task_id = payload.get("backfill_task_id")
        self.assertIsInstance(task_id, str)
        self.assertTrue(task_id.startswith("bf-"), task_id)
        self.assertEqual(payload.get("backfill_status"), "queued")
        self.assertIn("00700", self.application.repository.active_tickers())
        self.assertLess(elapsed, 2.0, f"batch returned in {elapsed:.2f}s")

    def test_batch_add_multi_market_single_backfill_task(self) -> None:
        application = WebApplication(
            self.project_root,
            collection_runner=self.noop_collection_runner,
        )
        slug = self._create_list(application)
        with patch.object(application, "hkexnews_resolver", _NoneResolver()):
            response = application.handle(
                "POST", "/api/companies/batch",
                json.dumps({"tickers": "AAPL 00700@HK", "lists": [slug]}).encode(),
            )
        payload = self.payload(response)
        self.assertEqual(response.status, 201)
        self.assertEqual(payload.get("backfill_status"), "queued")
        task_id = payload["backfill_task_id"]
        self.assertTrue(task_id.startswith("bf-"))

        task = self._wait_for_backfill(application, task_id)
        self.assertEqual(task["id"], task_id)
        self.assertEqual(task["market"], "us")
        self.assertEqual(task["markets"], {"AAPL": "us", "00700": "hk"})
        self.assertEqual(set(task["tickers"]), {"AAPL", "00700"})
        self.assertEqual(task["sources"], ["sec"])
        self.assertIn(task["status"], TERMINAL_STATUSES)
        self.assertIsNotNone(task["summary"])

        missing = application.handle("GET", "/api/backfill-tasks/bf-does-not-exist")
        self.assertEqual(missing.status, 404)
        self.assertIn("error", self.payload(missing))


if __name__ == "__main__":
    unittest.main()
