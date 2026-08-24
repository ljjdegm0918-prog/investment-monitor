"""Seeded test logins 1-5: created from web.main(), not WebApplication.__init__."""

from __future__ import annotations

import json
import sqlite3
import time
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from investment_monitor.application import ConfiguredCollectionResult, SaveResult
from investment_monitor.auth import LEGACY_LOCAL_SUBJECT, SEED_LOGINS
from investment_monitor.web import SESSION_COOKIE_NAME, WebApplication

HOST_HEADERS = {"Host": "127.0.0.1:8765"}
LOGIN_HEADERS = {
    "Content-Type": "application/json",
    "Host": "127.0.0.1:8765",
    "Origin": "http://127.0.0.1:8765",
}
FIXED_NOW = datetime(2026, 8, 25, 12, 0, tzinfo=timezone.utc)
PASSWORDS = {
    username: password for username, password, _display, _role in SEED_LOGINS
}


def _session_cookie_value(response) -> str:
    cookies = [value for name, value in response.headers if name == "Set-Cookie"]
    assert cookies, "expected a Set-Cookie header"
    return cookies[0].split(";", 1)[0]


class SeedLoginTests(unittest.TestCase):
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
            "ticker,list_type\nAAPL,holdings\nMSFT,holdings\n",
            encoding="utf-8",
        )
        cache_directory = self.project_root / ".cache" / "investment_monitor"
        cache_directory.mkdir(parents=True)
        (cache_directory / "company_tickers.json").write_text(json.dumps({
            "0": {"cik_str": 320193, "ticker": "AAPL", "title": "Apple Inc."},
            "1": {"cik_str": 789019, "ticker": "MSFT", "title": "Microsoft Corporation"},
        }), encoding="utf-8")
        self.application = WebApplication(
            self.project_root,
            collection_runner=self.recording_collection_runner,
            clock=lambda: FIXED_NOW,
        )

    def tearDown(self) -> None:
        self.application.research.shutdown()
        self.application.shutdown_user_research()
        for _ in range(10):
            try:
                self.temporary_directory.cleanup()
                return
            except PermissionError:
                time.sleep(0.1)
        self.temporary_directory.cleanup()

    def recording_collection_runner(self, **kwargs):
        return ConfiguredCollectionResult(
            items=(), failures=(), save_result=SaveResult(),
            database_path=self.project_root / "data" / "web.sqlite3",
            stored_count=0,
        )

    def payload(self, response):
        return json.loads(response.body.decode("utf-8"))

    def login(self, username: str, password: str):
        return self.application.handle(
            "POST", "/api/login",
            json.dumps({"username": username, "password": password}).encode(),
            headers=LOGIN_HEADERS, client_ip="203.0.113.7",
        )

    def auth_headers(self, username: str, password: str):
        response = self.login(username, password)
        self.assertEqual(response.status, 200, self.payload(response))
        cookie = _session_cookie_value(response)
        self.assertIn(SESSION_COOKIE_NAME, cookie)
        return {**HOST_HEADERS, "Cookie": cookie}

    def add_company(self, ticker: str, headers) -> None:
        response = self.application.handle(
            "POST", "/api/companies/batch",
            json.dumps({"tickers": ticker, "lists": ["holdings"]}).encode(),
            headers={**headers, "Content-Type": "application/json",
                     "Origin": "http://127.0.0.1:8765"},
        )
        self.assertIn(response.status, (200, 201), self.payload(response))
        task_id = self.payload(response).get("backfill_task_id")
        if not task_id:
            return
        for _ in range(100):
            status = self.payload(self.application.handle(
                "GET", f"/api/backfill-tasks/{task_id}", headers=headers
            ))
            if status["status"] in ("success", "partial", "failure"):
                return
            time.sleep(0.02)

    def test_web_application_init_does_not_seed_accounts(self):
        self.assertFalse(self.application._sessions.has_login_accounts())

    def test_ensure_seed_logins_creates_five_distinct_accounts(self):
        result = self.application._sessions.ensure_seed_logins()
        self.assertEqual(result["created"], ["1", "2", "3", "4", "5"])
        self.assertEqual(result["skipped"], [])

        accounts = {
            account["username"]: account
            for account in self.application._sessions.accounts()
        }
        self.assertEqual(accounts["1"]["role"], "admin")
        for username in ("2", "3", "4", "5"):
            self.assertEqual(accounts[username]["role"], "user")
        serialized = json.dumps(list(accounts.values()))
        self.assertNotIn("password_hash", serialized)
        self.assertNotIn("$argon2", serialized)

        database = self.project_root / "data" / "web.sqlite3"
        with closing(sqlite3.connect(database)) as connection:
            rows = connection.execute(
                "SELECT username, subject FROM users WHERE username IS NOT NULL"
            ).fetchall()
        subjects = {username: subject for username, subject in rows}
        self.assertEqual(subjects["1"], "login:1")
        self.assertNotIn(LEGACY_LOCAL_SUBJECT, subjects.values())

        for username, password, _display, _role in SEED_LOGINS:
            self.assertEqual(self.login(username, password).status, 200, username)

        admin_headers = self.auth_headers("1", PASSWORDS["1"])
        settings = self.application.handle(
            "GET", "/api/settings", headers=admin_headers
        )
        self.assertEqual(settings.status, 200)

        member_headers = self.auth_headers("2", PASSWORDS["2"])
        forbidden = self.application.handle(
            "GET", "/api/settings", headers=member_headers
        )
        self.assertEqual(forbidden.status, 403)

        listing = self.application.handle(
            "GET", "/api/admin/users", headers=admin_headers
        )
        self.assertEqual(listing.status, 200)
        self.assertNotIn("password_hash", json.dumps(self.payload(listing)))

    def test_ensure_seed_logins_is_idempotent(self):
        self.application._sessions.ensure_seed_logins()
        again = self.application._sessions.ensure_seed_logins()
        self.assertEqual(again["created"], [])
        self.assertEqual(again["skipped"], ["1", "2", "3", "4", "5"])
        self.assertEqual(self.login("1", PASSWORDS["1"]).status, 200)
        self.assertEqual(len(self.application._sessions.accounts()), 5)

    def test_seeded_users_do_not_share_holdings(self):
        self.application._sessions.ensure_seed_logins()
        user_two = self.auth_headers("2", PASSWORDS["2"])
        user_three = self.auth_headers("3", PASSWORDS["3"])
        self.add_company("AAPL", user_two)

        two_companies = self.payload(
            self.application.handle("GET", "/api/companies", headers=user_two)
        )["companies"]
        three_companies = self.payload(
            self.application.handle("GET", "/api/companies", headers=user_three)
        )["companies"]
        self.assertIn("AAPL", [company["ticker"] for company in two_companies])
        self.assertNotIn("AAPL", [company["ticker"] for company in three_companies])
