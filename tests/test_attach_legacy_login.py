"""CLI test: ``investment-monitor attach-legacy-login`` (work-order item 8).

One successful attach, a refused second attempt, and the resulting login sees
the historical holdings that belonged to the legacy-local owner.
"""

from __future__ import annotations

import json
import os
import sqlite3
from contextlib import closing
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from investment_monitor.cli import main
from investment_monitor.web import SESSION_COOKIE_NAME, WebApplication

LEGACY_PASSWORD = "legacy-attach-pass-1"
ENV_NAME = "IM_ATTACH_LEGACY_PASSWORD"
LOGIN_HEADERS = {
    "Content-Type": "application/json",
    "Host": "127.0.0.1:8765",
    "Origin": "http://127.0.0.1:8765",
}


class AttachLegacyLoginCliTests(unittest.TestCase):
    """The CLI primitive is opt-in and never runs on the default path."""

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
            "ticker,list_type\nAAPL,holdings\n",
            encoding="utf-8",
        )
        cache_directory = self.project_root / ".cache" / "investment_monitor"
        cache_directory.mkdir(parents=True)
        (cache_directory / "company_tickers.json").write_text(json.dumps({
            "0": {"cik_str": 320193, "ticker": "AAPL", "title": "Apple Inc."},
        }), encoding="utf-8")
        self.application = WebApplication(self.project_root)
        self.settings_path = self.project_root / "config" / "settings.yaml"

    def tearDown(self) -> None:
        os.environ.pop(ENV_NAME, None)
        self.application.research.shutdown()
        self.application.shutdown_user_research()
        self._cleanup_with_retry()

    def _cleanup_with_retry(self) -> None:
        import time
        for _ in range(10):
            try:
                self.temporary_directory.cleanup()
                return
            except PermissionError:
                time.sleep(0.1)
        self.temporary_directory.cleanup()

    def run_cli(self, username: str) -> None:
        os.environ[ENV_NAME] = LEGACY_PASSWORD
        # The console entry point dispatches the sub-command exactly like
        # ``investment-monitor attach-legacy-login ...`` on a real shell.
        main([
            "attach-legacy-login",
            "--username", username,
            "--settings", str(self.settings_path),
        ])

    def test_attach_once_then_refused_and_login_sees_old_holdings(self):
        # Before attaching, nobody can log in and legacy data stays put.
        self.assertFalse(self.application._sessions.has_login_accounts())

        self.run_cli("Boss")
        accounts = self.application._sessions.accounts()
        self.assertEqual(len(accounts), 1)
        self.assertEqual(accounts[0]["username"], "boss")
        self.assertEqual(accounts[0]["role"], "admin")
        self.assertEqual(accounts[0]["status"], "active")

        # A second attach must be refused: the legacy row is already bound.
        with self.assertRaises(SystemExit):
            self.run_cli("boss")
        with self.assertRaises(SystemExit):
            self.run_cli("someone-else")
        self.assertEqual(len(self.application._sessions.accounts()), 1)

        # Logging in with the attached account sees the historical holdings.
        response = self.application.handle(
            "POST", "/api/login",
            json.dumps({
                "username": "BOSS", "password": LEGACY_PASSWORD,
            }).encode(),
            headers=LOGIN_HEADERS,
        )
        self.assertEqual(response.status, 200)
        cookie = [
            value for name, value in response.headers if name == "Set-Cookie"
        ][0].split(";", 1)[0]
        self.assertIn(SESSION_COOKIE_NAME, cookie)

        companies = json.loads(self.application.handle(
            "GET", "/api/companies",
            headers={"Host": "127.0.0.1:8765", "Cookie": cookie},
        ).body.decode("utf-8"))["companies"]
        self.assertIn(
            "AAPL", [company["ticker"] for company in companies],
            "the attached login must see the legacy holdings import",
        )

    def test_cli_refuses_when_username_is_taken(self):
        # Username already taken by a regular account -> refused.
        self.application._sessions.create_account(
            "taken", "already-taken-pass", "Taken"
        )
        with self.assertRaises(SystemExit):
            self.run_cli("taken")
        # The legacy row keeps its data and stays unattached.
        with closing(sqlite3.connect(
            self.project_root / "data" / "web.sqlite3"
        )) as connection:
            row = connection.execute(
                "SELECT username, status FROM users WHERE subject = ?",
                ("legacy-local",),
            ).fetchone()
        self.assertIsNotNone(row)
        self.assertIsNone(row[0])
        self.assertEqual(row[1], "legacy")


if __name__ == "__main__":
    unittest.main()
