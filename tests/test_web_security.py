"""Security hardening tests: web auth token and extra_env whitelist.

These tests intentionally fail until Task 2/3 implement the hardening:
- WEB_AUTH_TOKEN gate for /api/*
- extra_env whitelist rejecting secret/url/tls override names
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import tempfile
import threading
import unittest
import urllib.request

from investment_monitor.application import ConfiguredCollectionResult, SaveResult
from investment_monitor.web import WebApplication


class WebSecurityTests(unittest.TestCase):
    """Focused security tests against a throwaway project directory."""

    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.project_root = Path(self.temporary_directory.name)
        (self.project_root / "config").mkdir()
        (self.project_root / "data").mkdir()
        (self.project_root / "config" / "settings.yaml").write_text(
            "enabled_sources:\n  - sec\ndatabase_path: ../data/web.sqlite3\n",
            encoding="utf-8",
        )
        (self.project_root / "config" / "universe.csv").write_text(
            "ticker,list_type\nAAPL,holdings\n", encoding="utf-8",
        )
        cache_directory = self.project_root / ".cache" / "investment_monitor"
        cache_directory.mkdir(parents=True)
        (cache_directory / "company_tickers.json").write_text(
            json.dumps({
                "0": {"cik_str": 320193, "ticker": "AAPL", "title": "Apple Inc."},
            }),
            encoding="utf-8",
        )
        self.application = WebApplication(
            self.project_root,
            collection_runner=self.noop_collection_runner,
        )

    def tearDown(self) -> None:
        # 清理鉴权与 extra_env 测试可能注入进程的环境变量，保持用例隔离。
        for env_name in (
            "WEB_AUTH_TOKEN",
            "RESEARCH_AI_BASE_URL",
            "RESEARCH_AI_ALLOWED_HOSTS",
            "RESEARCH_AI_API_KEY",
            "FINNHUB_BASE_URL",
            "AU_UNIVERSE_VERIFY_SSL",
            "MY_APP_TOKEN",
            "XUEQIU_COOKIE",
            "SEC_USER_AGENT",
            "ADD_COMPANY_BACKFILL_DAYS",
        ):
            os.environ.pop(env_name, None)
        self.temporary_directory.cleanup()

    def noop_collection_runner(self, **kwargs):
        return ConfiguredCollectionResult(
            items=(),
            failures=(),
            save_result=SaveResult(),
            database_path=self.project_root / "data" / "web.sqlite3",
            stored_count=0,
        )

    def payload(self, response):
        return json.loads(response.body.decode("utf-8"))

    def post_setting(self, key: str, value: str):
        return self.application.handle(
            "POST",
            "/api/settings",
            json.dumps({"key": key, "value": value}).encode(),
        )

    # --- HIGH-01: WEB_AUTH_TOKEN -------------------------------------------------

    def test_web_auth_token_requires_bearer_for_api(self) -> None:
        os.environ["WEB_AUTH_TOKEN"] = "test-secret"
        response = self.application.handle(
            "GET",
            "/api/settings",
            headers={"Host": "127.0.0.1:8765"},
        )
        self.assertEqual(response.status, 401)
        self.assertEqual(self.payload(response)["code"], "web_auth_required")

    def test_web_auth_token_accepts_correct_bearer(self) -> None:
        os.environ["WEB_AUTH_TOKEN"] = "test-secret"
        response = self.application.handle(
            "GET",
            "/api/settings",
            headers={
                "Host": "127.0.0.1:8765",
                "Authorization": "Bearer test-secret",
            },
        )
        self.assertEqual(response.status, 200)
        self.assertIn("extra_env", self.payload(response))

    def test_web_auth_token_rejects_wrong_bearer(self) -> None:
        os.environ["WEB_AUTH_TOKEN"] = "test-secret"
        response = self.application.handle(
            "GET",
            "/api/settings",
            headers={
                "Host": "127.0.0.1:8765",
                "Authorization": "Bearer wrong",
            },
        )
        self.assertEqual(response.status, 401)

    def test_web_auth_token_unset_keeps_local_compatibility(self) -> None:
        os.environ.pop("WEB_AUTH_TOKEN", None)
        response = self.application.handle("GET", "/api/settings")
        self.assertEqual(response.status, 200)

    def test_web_auth_token_does_not_gate_html_pages(self) -> None:
        os.environ["WEB_AUTH_TOKEN"] = "test-secret"
        response = self.application.handle(
            "GET",
            "/manage",
            headers={"Host": "127.0.0.1:8765"},
        )
        self.assertEqual(response.status, 200)
        self.assertIn(b"Investment Monitor", response.body)

    # --- HIGH-03: extra_env whitelist -------------------------------------------

    def test_extra_env_rejects_secret_and_url_and_tls_names(self) -> None:
        for bad_key in (
            "extra_env:RESEARCH_AI_BASE_URL",
            "extra_env:RESEARCH_AI_ALLOWED_HOSTS",
            "extra_env:RESEARCH_AI_API_KEY",
            "extra_env:FINNHUB_BASE_URL",
            "extra_env:AU_UNIVERSE_VERIFY_SSL",
            "extra_env:MY_APP_TOKEN",
            "extra_env:XUEQIU_COOKIE",
            "extra_env:SEC_USER_AGENT",
        ):
            with self.subTest(bad_key=bad_key):
                response = self.post_setting(bad_key, "x")
                self.assertEqual(response.status, 400, bad_key)

    def test_extra_env_allows_whitelisted_tuning_name(self) -> None:
        env_name = "ADD_COMPANY_BACKFILL_DAYS"
        try:
            response = self.post_setting(f"extra_env:{env_name}", "30")
            self.assertEqual(response.status, 200)
            self.assertEqual(os.environ.get(env_name), "30")
        finally:
            os.environ.pop(env_name, None)
            self.post_setting(f"extra_env:{env_name}", "")

    # --- MED-04: security response headers ------------------------------------

    def test_security_response_headers_served_on_http(self) -> None:
        from investment_monitor.web import InvestmentMonitorHandler, ThreadingHTTPServer

        InvestmentMonitorHandler.application = self.application
        server = ThreadingHTTPServer(("127.0.0.1", 0), InvestmentMonitorHandler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            with urllib.request.urlopen(
                f"http://127.0.0.1:{server.server_port}/",
                timeout=5,
            ) as response:
                self.assertEqual(response.status, 200)
                self.assertEqual(response.headers["X-Frame-Options"], "DENY")
                self.assertEqual(
                    response.headers["X-Content-Type-Options"], "nosniff"
                )
                self.assertEqual(response.headers["Referrer-Policy"], "same-origin")
                csp = response.headers["Content-Security-Policy"]
                self.assertIn("default-src 'self'", csp)
                self.assertIn("script-src 'self'", csp)
                self.assertIn("frame-ancestors 'none'", csp)
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)


if __name__ == "__main__":
    unittest.main()
