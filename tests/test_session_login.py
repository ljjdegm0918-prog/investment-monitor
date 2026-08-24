"""Session login, per-user isolation, and instance-level key vault tests.

Covers work-order items:
1. empty-database startup keeps legacy lists away from new logins
2. per-user company isolation with a shared information pool
3. forged / expired / revoked cookies are rejected
4. user_id smuggled in a request body cannot switch identity
5. /api/admin/users requires an admin session
6. login rate limiting answers 429
7. a password change revokes every session of that user
9/10. the collection union spans users and collects a shared company once
11/12. only admins read/write instance keys; no per-user key fields exist
"""

from __future__ import annotations

import json
import os
import sqlite3
from contextlib import closing
from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest import mock

from investment_monitor.application import ConfiguredCollectionResult, SaveResult
from investment_monitor.models import InformationItem
from investment_monitor.sqlite_repository import SQLiteInformationRepository
from investment_monitor.web import SESSION_COOKIE_NAME, WebApplication

HOST_HEADERS = {"Host": "127.0.0.1:8765"}
LOGIN_HEADERS = {
    "Content-Type": "application/json",
    "Host": "127.0.0.1:8765",
    "Origin": "http://127.0.0.1:8765",
}
SAME_ORIGIN_HEADERS = dict(LOGIN_HEADERS)
FIXED_NOW = datetime(2026, 8, 25, 12, 0, tzinfo=timezone.utc)
ADMIN_PASSWORD = "correct-horse-battery"


def _session_cookie_value(response) -> str:
    cookies = [value for name, value in response.headers if name == "Set-Cookie"]
    assert cookies, "expected a Set-Cookie header"
    return cookies[0].split(";", 1)[0]


class SessionLoginTests(unittest.TestCase):
    """Login contract and account lifecycle over a throwaway project."""

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
        self.fake_now = FIXED_NOW
        self.collection_calls = []
        self.application = WebApplication(
            self.project_root,
            collection_runner=self.recording_collection_runner,
            clock=lambda: self.fake_now,
        )

    def tearDown(self) -> None:
        for env_name in ("WEB_EXTERNAL_SCHEME",):
            os.environ.pop(env_name, None)
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

    def recording_collection_runner(self, **kwargs):
        self.collection_calls.append(kwargs)
        return ConfiguredCollectionResult(
            items=(), failures=(), save_result=SaveResult(),
            database_path=self.project_root / "data" / "web.sqlite3",
            stored_count=0,
        )

    def payload(self, response):
        return json.loads(response.body.decode("utf-8"))

    # -- provisioning helpers -------------------------------------------

    def provision_admin(self) -> None:
        """Create the first administrator exactly like a real deployment."""
        self.application._sessions.create_account(
            "boss", ADMIN_PASSWORD, "Boss", role="admin"
        )

    def create_member(self, username: str, password: str) -> None:
        self.application._sessions.create_account(username, password, username)

    def login(self, username: str, password: str, client_ip: str = "203.0.113.7"):
        return self.application.handle(
            "POST", "/api/login",
            json.dumps({"username": username, "password": password}).encode(),
            headers=LOGIN_HEADERS, client_ip=client_ip,
        )

    def auth_headers(self, username: str, password: str):
        response = self.login(username, password)
        assert response.status == 200, self.payload(response)
        cookie = _session_cookie_value(response)
        assert SESSION_COOKIE_NAME in cookie
        return {"Host": "127.0.0.1:8765", "Cookie": cookie}

    # --- item 1: empty-database startup ----------------------------------

    def test_empty_database_keeps_legacy_lists_hidden_from_new_logins(self):
        # The legacy owner keeps its three fixed lists and the universe import.
        legacy_repository = self.application.repository
        self.assertEqual(
            [record["slug"] for record in legacy_repository.fixed_lists()],
            ["holdings", "planned", "watchlist"],
        )
        self.assertTrue(legacy_repository.companies())

        self.provision_admin()
        self.create_member("alice", "alice-pass-123")
        headers = self.auth_headers("alice", "alice-pass-123")

        bootstrap = self.payload(self.application.handle(
            "GET", "/api/bootstrap", headers=headers
        ))
        # A fresh login sees its own empty fixed lists, never legacy data.
        self.assertEqual(bootstrap["user"]["username"], "alice")
        self.assertEqual(len(bootstrap["lists"]), 3)
        for list_record in bootstrap["lists"]:
            self.assertEqual(list_record["company_count"], 0)
        self.assertEqual(bootstrap["companies"], [])
        # The legacy holdings import stays invisible to the new login.
        self.assertNotIn(
            "AAPL", [company["ticker"] for company in bootstrap["companies"]]
        )

    def test_initial_admin_environment_creates_first_admin(self):
        with TemporaryDirectory() as root_name:
            root = Path(root_name)
            (root / "config").mkdir()
            (root / "data").mkdir()
            (root / "config" / "settings.yaml").write_text(
                "enabled_sources:\n  - sec\n"
                "database_path: ../data/web.sqlite3\n",
                encoding="utf-8",
            )
            (root / "config" / "universe.csv").write_text(
                "ticker,list_type\nAAPL,holdings\n", encoding="utf-8"
            )
            cache = root / ".cache" / "investment_monitor"
            cache.mkdir(parents=True)
            (cache / "company_tickers.json").write_text(json.dumps({
                "0": {"cik_str": 320193, "ticker": "AAPL", "title": "Apple Inc."},
            }), encoding="utf-8")
            env = {
                "INITIAL_ADMIN_USERNAME": "Founder",
                "INITIAL_ADMIN_PASSWORD": "founder-pass-1",
            }
            with mock.patch.dict(os.environ, env):
                application = WebApplication(
                    root, collection_runner=self.recording_collection_runner
                )
            try:
                accounts = application._sessions.accounts()
                self.assertEqual(len(accounts), 1)
                self.assertEqual(accounts[0]["username"], "founder")
                self.assertEqual(accounts[0]["role"], "admin")
                self.assertNotEqual(
                    accounts[0]["status"], "legacy",
                    "initial admin must not reuse the legacy row",
                )
                # Username was normalized to lower-case on creation.
                response = self.application.handle  # silence linters
                login = application.handle(
                    "POST", "/api/login",
                    json.dumps({
                        "username": "FOUNDER", "password": "founder-pass-1",
                    }).encode(),
                    headers=LOGIN_HEADERS,
                )
                self.assertEqual(login.status, 200)
            finally:
                application.research.shutdown()

    # --- item 3: forged / expired / revoked cookies ----------------------

    def test_forged_expired_and_revoked_cookies_are_rejected(self):
        self.provision_admin()
        self.create_member("alice", "alice-pass-123")
        headers = self.auth_headers("alice", "alice-pass-123")

        forged = {"Host": "127.0.0.1:8765", "Cookie": "im_session=not-a-real-token"}
        response = self.application.handle("GET", "/api/bootstrap", headers=forged)
        self.assertEqual(response.status, 401)
        self.assertEqual(self.payload(response)["code"], "session_required")

        # A session past its expiry is refused.
        self.fake_now = FIXED_NOW + timedelta(days=8)
        response = self.application.handle("GET", "/api/bootstrap", headers=headers)
        self.assertEqual(response.status, 401)
        self.fake_now = FIXED_NOW

        # Logout revokes the session; the same cookie stops working.
        logout = self.application.handle(
            "POST", "/api/logout", b"",
            headers={**headers, "Content-Type": "application/json",
                     "Origin": "http://127.0.0.1:8765"},
        )
        self.assertEqual(logout.status, 200)
        response = self.application.handle("GET", "/api/bootstrap", headers=headers)
        self.assertEqual(response.status, 401)

    def test_html_pages_redirect_to_login_and_login_page_is_open(self):
        self.provision_admin()
        response = self.application.handle(
            "GET", "/today", headers=HOST_HEADERS
        )
        self.assertEqual(response.status, 302)
        self.assertIn(("Location", "/login"), response.headers)

        login_page = self.application.handle("GET", "/login", headers=HOST_HEADERS)
        self.assertEqual(login_page.status, 200)
        self.assertIn(b'data-view="login"', login_page.body)

        static = self.application.handle(
            "GET", "/static/app.css", headers=HOST_HEADERS
        )
        self.assertEqual(static.status, 200)

    def test_api_without_session_answers_session_required(self):
        self.provision_admin()
        response = self.application.handle(
            "GET", "/api/bootstrap", headers=HOST_HEADERS
        )
        self.assertEqual(response.status, 401)
        self.assertEqual(self.payload(response)["code"], "session_required")

    # --- session cookie contract ------------------------------------------

    def test_login_cookie_contract_and_no_token_in_body(self):
        self.provision_admin()
        self.create_member("alice", "alice-pass-123")
        response = self.login("alice", "alice-pass-123")
        self.assertEqual(response.status, 200)
        cookie = [v for n, v in response.headers if n == "Set-Cookie"][0]
        for attribute in ("HttpOnly", "SameSite=Lax", "Path=/", "Max-Age=604800"):
            self.assertIn(attribute, cookie)
        self.assertNotIn("Secure", cookie)  # WEB_EXTERNAL_SCHEME defaults to http
        body = self.payload(response)
        self.assertNotIn("token", json.dumps(body))

        os.environ["WEB_EXTERNAL_SCHEME"] = "https"
        secure_response = self.application.handle(
            "POST", "/api/login",
            json.dumps({"username": "alice", "password": "alice-pass-123"}).encode(),
            headers={**LOGIN_HEADERS, "Origin": "https://127.0.0.1:8765"},
        )
        self.assertEqual(secure_response.status, 200)
        secure_cookie = [
            v for n, v in secure_response.headers if n == "Set-Cookie"
        ][0]
        self.assertIn("Secure", secure_cookie)
        os.environ.pop("WEB_EXTERNAL_SCHEME", None)

        # Only sha256(token) reaches the database, never the raw token.
        database = self.project_root / "data" / "web.sqlite3"
        with closing(sqlite3.connect(database)) as connection:
            rows = connection.execute(
                "SELECT token_hash FROM sessions"
            ).fetchall()
        self.assertTrue(rows)
        raw_token = _session_cookie_value(response).split("=", 1)[1]
        self.assertNotIn((raw_token,), rows)

    def test_login_failures_are_generic_and_username_is_normalized(self):
        self.provision_admin()
        self.create_member("Alice", "alice-pass-123")

        unknown = self.login("nobody", "whatever-123")
        wrong_password = self.login("alice", "wrong-password")
        self.assertEqual(unknown.status, 401)
        self.assertEqual(wrong_password.status, 401)
        self.assertEqual(
            self.payload(unknown)["error"], self.payload(wrong_password)["error"]
        )

        # Case-insensitive login; the stored username stays lower-case.
        response = self.login("ALICE", "alice-pass-123")
        self.assertEqual(response.status, 200)
        self.assertEqual(self.payload(response)["user"]["username"], "alice")

    def test_disabled_account_cannot_login_or_use_sessions(self):
        self.provision_admin()
        self.create_member("alice", "alice-pass-123")
        headers = self.auth_headers("alice", "alice-pass-123")

        admin_headers = self.auth_headers("boss", ADMIN_PASSWORD)
        disable = self.application.handle(
            "POST", "/api/admin/users/status",
            json.dumps({"username": "alice", "status": "disabled"}).encode(),
            headers={**admin_headers, "Content-Type": "application/json",
                     "Origin": "http://127.0.0.1:8765"},
        )
        self.assertEqual(disable.status, 200)

        # Existing session stops resolving once the account is disabled.
        response = self.application.handle("GET", "/api/bootstrap", headers=headers)
        self.assertEqual(response.status, 401)
        self.assertEqual(self.login("alice", "alice-pass-123").status, 401)

    # --- item 5/6/7: admin endpoints, rate limiting, password rotation ----

    def test_admin_users_endpoint_requires_admin_session(self):
        self.provision_admin()
        self.create_member("alice", "alice-pass-123")
        member_headers = self.auth_headers("alice", "alice-pass-123")

        for method, body in (
            ("GET", b""),
            ("POST", json.dumps({
                "username": "mallory", "password": "evil-pass-123",
            }).encode()),
        ):
            with self.subTest(method=method):
                headers = dict(member_headers)
                if method == "POST":
                    headers["Content-Type"] = "application/json"
                    headers["Origin"] = "http://127.0.0.1:8765"
                response = self.application.handle(
                    method, "/api/admin/users", body, headers=headers
                )
                self.assertEqual(response.status, 403)
                self.assertEqual(self.payload(response)["code"], "admin_required")

    def test_admin_can_create_accounts_without_leaking_hashes(self):
        self.provision_admin()
        admin_headers = self.auth_headers("boss", ADMIN_PASSWORD)
        response = self.application.handle(
            "POST", "/api/admin/users",
            json.dumps({
                "username": "Bob", "password": "bob-pass-1234",
                "display_name": "Bob", "role": "user",
            }).encode(),
            headers={**admin_headers, "Content-Type": "application/json",
                     "Origin": "http://127.0.0.1:8765"},
        )
        self.assertEqual(response.status, 201)
        self.assertEqual(self.payload(response)["user"]["username"], "bob")

        listing = self.application.handle(
            "GET", "/api/admin/users", headers=admin_headers
        )
        serialized = json.dumps(self.payload(listing))
        self.assertNotIn("password_hash", serialized)
        self.assertNotIn("$argon2", serialized)

        duplicate = self.application.handle(
            "POST", "/api/admin/users",
            json.dumps({"username": "bob", "password": "bob-pass-1234"}).encode(),
            headers={**admin_headers, "Content-Type": "application/json",
                     "Origin": "http://127.0.0.1:8765"},
        )
        self.assertEqual(duplicate.status, 400)

    def test_login_rate_limit_answers_429(self):
        self.provision_admin()
        self.create_member("alice", "alice-pass-123")
        for _ in range(10):
            response = self.login("alice", "wrong-password", client_ip="198.51.100.9")
            self.assertEqual(response.status, 401)
        throttled = self.login(
            "alice", "alice-pass-123", client_ip="198.51.100.9"
        )
        self.assertEqual(throttled.status, 429)
        self.assertEqual(self.payload(throttled)["code"], "login_rate_limited")
        # A different client address is not throttled.
        self.assertEqual(
            self.login("alice", "alice-pass-123", client_ip="198.51.100.10").status,
            200,
        )

    def test_password_change_revokes_existing_sessions(self):
        self.provision_admin()
        self.create_member("alice", "alice-pass-123")
        old_headers = self.auth_headers("alice", "alice-pass-123")

        change = self.application.handle(
            "POST", "/api/account/password",
            json.dumps({
                "current_password": "alice-pass-123",
                "new_password": "brand-new-pass-9",
            }).encode(),
            headers={**old_headers, "Content-Type": "application/json",
                     "Origin": "http://127.0.0.1:8765"},
        )
        self.assertEqual(change.status, 200)

        response = self.application.handle(
            "GET", "/api/bootstrap", headers=old_headers
        )
        self.assertEqual(response.status, 401)
        self.assertEqual(self.login("alice", "alice-pass-123").status, 401)
        self.assertEqual(self.login("alice", "brand-new-pass-9").status, 200)

    # --- items 2/4: isolation and principal trust -------------------------

    def add_company(self, ticker: str, headers) -> None:
        response = self.application.handle(
            "POST", "/api/companies/batch",
            json.dumps({"tickers": ticker, "lists": ["holdings"]}).encode(),
            headers={**headers, "Content-Type": "application/json",
                     "Origin": "http://127.0.0.1:8765"},
        )
        self.assertIn(response.status, (200, 201), self.payload(response))
        task_id = self.payload(response).get("backfill_task_id")
        if task_id:
            self._wait_backfill(task_id, headers)

    def _wait_backfill(self, task_id: str, headers) -> None:
        import time
        for _ in range(100):
            status = self.payload(self.application.handle(
                "GET", f"/api/backfill-tasks/{task_id}", headers=headers
            ))
            if status["status"] in ("success", "partial", "failure"):
                return
            time.sleep(0.02)

    def test_user_companies_are_isolated_but_items_are_shared(self):
        self.provision_admin()
        self.create_member("alice", "alice-pass-123")
        self.create_member("bob", "bob-pass-1234")
        alice_headers = self.auth_headers("alice", "alice-pass-123")
        bob_headers = self.auth_headers("bob", "bob-pass-1234")

        self.add_company("AAPL", alice_headers)

        alice_companies = self.payload(self.application.handle(
            "GET", "/api/companies", headers=alice_headers
        ))["companies"]
        bob_companies = self.payload(self.application.handle(
            "GET", "/api/companies", headers=bob_headers
        ))["companies"]
        self.assertIn("AAPL", [company["ticker"] for company in alice_companies])
        self.assertNotIn("AAPL", [company["ticker"] for company in bob_companies])

        # The information pool is shared infrastructure: one stored item.
        items = SQLiteInformationRepository(
            self.project_root / "data" / "web.sqlite3"
        )
        items.save((InformationItem(
            source="sec", source_type="regulatory_filing",
            external_id="shared-1", tickers=("AAPL",), issuer="Apple Inc.",
            published_at=datetime(2026, 8, 25, tzinfo=timezone.utc),
            title="Apple filing", document_type="8-K",
            url="https://www.sec.gov/Archives/shared-1.htm",
            collected_at=datetime(2026, 8, 25, tzinfo=timezone.utc),
            raw_metadata={},
        ),))

        alice_feed = self.payload(self.application.handle(
            "GET", "/api/feed", headers=alice_headers
        ))
        self.assertEqual(
            [item["external_id"] for item in alice_feed["items"]], ["shared-1"]
        )
        with closing(sqlite3.connect(
            self.project_root / "data" / "web.sqlite3"
        )) as connection:
            count = connection.execute(
                "SELECT COUNT(*) FROM information_items "
                "WHERE external_id = 'shared-1'"
            ).fetchone()[0]
        self.assertEqual(count, 1)

    def test_user_id_in_body_cannot_switch_identity(self):
        self.provision_admin()
        self.create_member("alice", "alice-pass-123")
        self.create_member("bob", "bob-pass-1234")
        alice_headers = self.auth_headers("alice", "alice-pass-123")
        bob_headers = self.auth_headers("bob", "bob-pass-1234")
        alice_id = self.payload(self.application.handle(
            "GET", "/api/account", headers=alice_headers
        ))["user"]["id"]

        # Bob tries to add a company "as" Alice through a smuggled user_id.
        response = self.application.handle(
            "POST", "/api/companies/batch",
            json.dumps({
                "tickers": "MSFT", "lists": ["holdings"],
                "user_id": alice_id, "user": alice_id,
            }).encode(),
            headers={**bob_headers, "Content-Type": "application/json",
                     "Origin": "http://127.0.0.1:8765"},
        )
        self.assertIn(response.status, (200, 201))

        alice_companies = self.payload(self.application.handle(
            "GET", "/api/companies", headers=alice_headers
        ))["companies"]
        bob_companies = self.payload(self.application.handle(
            "GET", "/api/companies", headers=bob_headers
        ))["companies"]
        self.assertNotIn("MSFT", [c["ticker"] for c in alice_companies])
        self.assertIn("MSFT", [c["ticker"] for c in bob_companies])

    # --- CSV import must not cross user boundaries -----------------------

    def test_csv_import_groups_all_belong_to_the_importing_user(self):
        self.provision_admin()
        self.create_member("alice", "alice-pass-123")
        headers = self.auth_headers("alice", "alice-pass-123")
        legacy_before = sorted(
            (company["ticker"], tuple(sorted(company["list_slugs"])))
            for company in self.application._shared_repository.companies()
        )

        # Two (market, list) groups force the fan-out through more than one
        # internal batch call; both must land on the importing user.
        csv_text = "ticker,market,list\nMSFT,us,holdings\nAAPL,us,watchlist\n"
        response = self.application.handle(
            "POST", "/api/companies/csv",
            json.dumps({"csv": csv_text}).encode(),
            headers={**headers, "Content-Type": "application/json",
                     "Origin": "http://127.0.0.1:8765"},
        )
        self.assertEqual(response.status, 201, self.payload(response))
        payload = self.payload(response)
        self.assertEqual(payload["failed"], [])
        self.assertEqual(len(payload["added"]), 2)

        alice_companies = {
            company["ticker"]: sorted(company["list_slugs"])
            for company in self.payload(self.application.handle(
                "GET", "/api/companies", headers=headers
            ))["companies"]
        }
        self.assertEqual(alice_companies.get("MSFT"), ["holdings"])
        self.assertEqual(alice_companies.get("AAPL"), ["watchlist"])

        # Nothing leaked into the legacy/shared scope: still only the
        # universe import in its original lists.
        legacy_after = sorted(
            (company["ticker"], tuple(sorted(company["list_slugs"])))
            for company in self.application._shared_repository.companies()
        )
        self.assertEqual(legacy_after, legacy_before)

    # --- items 9/10: collection union -------------------------------------

    def test_collection_union_spans_users_and_collects_once(self):
        self.provision_admin()
        self.create_member("alice", "alice-pass-123")
        self.create_member("bob", "bob-pass-1234")
        alice_headers = self.auth_headers("alice", "alice-pass-123")
        bob_headers = self.auth_headers("bob", "bob-pass-1234")

        self.add_company("AAPL", alice_headers)
        self.add_company("MSFT", bob_headers)
        # Both users watch the same company: it must still be collected once.
        self.add_company("AAPL", bob_headers)

        union = self.application.repository.active_companies()
        self.assertEqual(sorted(union), [("AAPL", "us"), ("MSFT", "us")])

        self.collection_calls.clear()
        summary = self.application.collect_active_companies(lookback_days=7)
        self.assertEqual(
            sorted(summary["tickers"]), ["AAPL", "MSFT"],
        )
        # One collection pass over the deduplicated union: AAPL appears once
        # even though two users watch it.
        self.assertEqual(len(self.collection_calls), 1)
        collected_tickers = tuple(self.collection_calls[0]["tickers"])
        self.assertEqual(collected_tickers.count("AAPL"), 1)
        self.assertIn("MSFT", collected_tickers)

    # --- items 11/12: instance-level key vault ----------------------------

    def test_regular_user_cannot_touch_instance_keys(self):
        self.provision_admin()
        self.create_member("alice", "alice-pass-123")
        member_headers = self.auth_headers("alice", "alice-pass-123")

        read = self.application.handle(
            "GET", "/api/settings", headers=member_headers
        )
        self.assertEqual(read.status, 403)
        self.assertEqual(self.payload(read)["code"], "admin_required")

        write = self.application.handle(
            "POST", "/api/settings",
            json.dumps({"key": "SEC_USER_AGENT", "value": "sk-test"}).encode(),
            headers={**member_headers, "Content-Type": "application/json",
                     "Origin": "http://127.0.0.1:8765"},
        )
        self.assertEqual(write.status, 403)

    def test_admin_writes_instance_key_used_by_collection(self):
        self.provision_admin()
        admin_headers = self.auth_headers("boss", ADMIN_PASSWORD)
        try:
            write = self.application.handle(
                "POST", "/api/settings",
                json.dumps({"key": "SEC_USER_AGENT", "value": "sk-test"}).encode(),
                headers={**admin_headers, "Content-Type": "application/json",
                         "Origin": "http://127.0.0.1:8765"},
            )
            self.assertEqual(write.status, 200)
            # The connector reads the instance-level value, not a user field.
            self.assertEqual(os.environ.get("SEC_USER_AGENT"), "sk-test")
            read = self.application.handle(
                "GET", "/api/settings", headers=admin_headers
            )
            self.assertEqual(read.status, 200)
            statuses = {
                field["env"]: field["configured"]
                for provider in self.payload(read)["providers"]
                for field in provider["fields"]
            }
            self.assertTrue(statuses["SEC_USER_AGENT"])
        finally:
            os.environ.pop("SEC_USER_AGENT", None)

    def test_no_per_user_key_fields_exist_anywhere(self):
        database = self.project_root / "data" / "web.sqlite3"
        with closing(sqlite3.connect(database)) as connection:
            user_columns = [
                row[1] for row in connection.execute("PRAGMA table_info(users)")
            ]
            tables = {
                row[0] for row in connection.execute(
                    "SELECT name FROM sqlite_master WHERE type = 'table'"
                )
            }
        self.assertFalse(
            any("key" in column or "secret" in column for column in user_columns),
            user_columns,
        )
        self.assertFalse(
            any("key" in table or "credential" in table for table in tables),
            tables,
        )


if __name__ == "__main__":
    unittest.main()
