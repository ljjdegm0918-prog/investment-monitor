"""Login accounts and session primitives for the multi-user web app.

This layer maps a verified session cookie to a trusted server-side principal
(``user_id``).  Browsers never choose the principal: ``user_id`` is never
read from query strings, request bodies, localStorage, or custom headers.

Design constraints carried over from the data-foundation plan:

- passwords are hashed with Argon2id; only hashes are stored;
- sessions store ``sha256(token)`` only, never the raw token;
- the ``legacy-local`` row keeps old single-user data and never becomes the
  implicit owner of new logged-in traffic;
- connector credentials stay instance-level; this module never touches them.
"""

from __future__ import annotations

import hashlib
import logging
import os
import secrets
import sqlite3
import threading
from contextlib import closing
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Mapping, Optional

from argon2 import PasswordHasher
from argon2.exceptions import Argon2Error

from .user_repository import LEGACY_LOCAL_SUBJECT, utc_now
from .web_repository import FIXED_LISTS

LOGGER = logging.getLogger(__name__)

ROLE_ADMIN = "admin"
ROLE_USER = "user"
ROLES = frozenset({ROLE_ADMIN, ROLE_USER})
# Private-repo test logins created on web startup. Passwords are documented
# in README.md / README_ZH.md; do not copy cloud/nginx/API secrets here.
SEED_LOGINS: tuple[tuple[str, str, str, str], ...] = (
    ("1", "Rk8nM2wQ7pLx", "用户1", ROLE_ADMIN),
    ("2", "Hj4cT9bV3sNw", "用户2", ROLE_USER),
    ("3", "Pq6fD1yK8mZr", "用户3", ROLE_USER),
    ("4", "Wb3gL7xC5nHs", "用户4", ROLE_USER),
    ("5", "Yt2sF8qN4vJm", "用户5", ROLE_USER),
)
ACCOUNT_STATUSES = frozenset({"active", "disabled"})
SESSION_COOKIE_NAME = "im_session"
SESSION_TTL = timedelta(days=7)
LOGIN_RATE_WINDOW = timedelta(minutes=15)
LOGIN_RATE_MAX_FAILURES = 10
MINIMUM_PASSWORD_LENGTH = 8

_HASHER = PasswordHasher()
# Verifying against this precomputed hash equalizes timing for unknown
# usernames so response latency does not reveal which accounts exist.
_DUMMY_HASH = _HASHER.hash("timing-equalization-placeholder")


class LoginError(Exception):
    """Generic authentication failure with an account-agnostic message."""


class LoginRateLimited(LoginError):
    """Too many failed login attempts from the same client address."""


class AccountError(Exception):
    """Account provisioning or maintenance failure."""


def normalize_username(username: str) -> str:
    """Usernames are stored and matched lower-case."""
    return str(username or "").strip().lower()


def hash_password(password: str) -> str:
    return _HASHER.hash(str(password))


def verify_password(password_hash: str, password: str) -> bool:
    """Constant-time Argon2id verification; malformed hashes simply fail."""
    target = password_hash or _DUMMY_HASH
    try:
        return _HASHER.verify(target, str(password))
    except Argon2Error:
        return False


def token_hash(token: str) -> str:
    """Only the sha256 of a session token is ever stored."""
    return hashlib.sha256(str(token).encode("utf-8")).hexdigest()


def validate_password_strength(password: str) -> None:
    if len(str(password or "")) < MINIMUM_PASSWORD_LENGTH:
        raise AccountError(
            f"password must be at least {MINIMUM_PASSWORD_LENGTH} characters"
        )


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _parse_timestamp(value: Any) -> datetime:
    return _as_utc(datetime.fromisoformat(str(value)))


class SessionGate:
    """Argon2id accounts and sha256-token sessions over the shared SQLite.

    One instance per process; every method opens its own short-lived
    connection so request threads and the collection scheduler never share
    sqlite connection objects.
    """

    def __init__(
        self,
        database_path: Path,
        *,
        clock: Optional[Callable[[], datetime]] = None,
        rate_window: timedelta = LOGIN_RATE_WINDOW,
        rate_max_failures: int = LOGIN_RATE_MAX_FAILURES,
    ) -> None:
        self._database_path = Path(database_path)
        self._clock = clock if clock is not None else (
            lambda: datetime.now(timezone.utc)
        )
        self._rate_window = rate_window
        self._rate_max_failures = rate_max_failures
        self._failures: Dict[str, List[float]] = {}
        self._failures_lock = threading.Lock()

    # -- connection helpers -------------------------------------------------

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self._database_path)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        return connection

    def _now(self) -> datetime:
        return _as_utc(self._clock())

    # -- login rate limiting (in-memory, injectable clock) ------------------

    def _prune_and_count(self, remote_ip: str) -> int:
        cutoff = (self._now() - self._rate_window).timestamp()
        with self._failures_lock:
            attempts = [
                stamp
                for stamp in self._failures.get(remote_ip, ())
                if stamp > cutoff
            ]
            if attempts:
                self._failures[remote_ip] = attempts
            else:
                self._failures.pop(remote_ip, None)
            return len(attempts)

    def _record_failure(self, remote_ip: str) -> None:
        with self._failures_lock:
            self._failures.setdefault(remote_ip, []).append(self._now().timestamp())

    def _clear_failures(self, remote_ip: str) -> None:
        with self._failures_lock:
            self._failures.pop(remote_ip, None)

    # -- authentication ------------------------------------------------------

    def login(
        self,
        username: str,
        password: str,
        remote_ip: str = "unknown",
    ) -> tuple:
        """Return ``(principal, token)`` or raise a generic LoginError."""
        if self._prune_and_count(remote_ip) >= self._rate_max_failures:
            raise LoginRateLimited("Too many failed login attempts")
        normalized = normalize_username(username)
        with closing(self._connect()) as connection:
            row = connection.execute(
                """SELECT id, username, display_name, role, status, password_hash
                   FROM users WHERE username = ?""",
                (normalized,),
            ).fetchone()
        stored_hash = str(row["password_hash"] or "") if row is not None else ""
        password_ok = verify_password(stored_hash, password)
        if row is None or str(row["status"]) != "active" or not password_ok:
            # Identical error for unknown user, legacy/disabled account, and
            # wrong password; the failed attempt still counts for rate limits.
            self._record_failure(remote_ip)
            raise LoginError("Invalid username or password")
        self._clear_failures(remote_ip)
        principal = {
            "user_id": int(row["id"]),
            "username": str(row["username"]),
            "display_name": str(row["display_name"]),
            "role": str(row["role"]),
        }
        token = self.create_session(principal["user_id"])
        return principal, token

    def create_session(self, user_id: int) -> str:
        token = secrets.token_urlsafe(32)
        now = self._now()
        expires = now + SESSION_TTL
        with closing(self._connect()) as connection:
            connection.execute(
                """INSERT INTO sessions (token_hash, user_id, created_at, expires_at)
                   VALUES (?, ?, ?, ?)""",
                (token_hash(token), user_id, now.isoformat(), expires.isoformat()),
            )
            connection.commit()
        return token

    def resolve_token(self, token: str) -> Optional[Dict[str, Any]]:
        """Return the principal for a live session token, else ``None``."""
        if not token:
            return None
        with closing(self._connect()) as connection:
            row = connection.execute(
                """SELECT s.expires_at AS expires_at, s.revoked_at AS revoked_at,
                          u.id AS user_id, u.username AS username,
                          u.display_name AS display_name, u.role AS role,
                          u.status AS status
                   FROM sessions s
                   JOIN users u ON u.id = s.user_id
                   WHERE s.token_hash = ?""",
                (token_hash(token),),
            ).fetchone()
        if row is None or row["revoked_at"]:
            return None
        if _parse_timestamp(row["expires_at"]) <= self._now():
            return None
        if str(row["status"]) != "active":
            return None
        return {
            "user_id": int(row["user_id"]),
            "username": str(row["username"]),
            "display_name": str(row["display_name"]),
            "role": str(row["role"]),
        }

    def logout(self, token: str) -> None:
        if not token:
            return
        now = self._now().isoformat()
        with closing(self._connect()) as connection:
            connection.execute(
                "UPDATE sessions SET revoked_at = ? "
                "WHERE token_hash = ? AND revoked_at IS NULL",
                (now, token_hash(token)),
            )
            connection.commit()

    def revoke_user_sessions(self, user_id: int) -> None:
        now = self._now().isoformat()
        with closing(self._connect()) as connection:
            connection.execute(
                "UPDATE sessions SET revoked_at = ? "
                "WHERE user_id = ? AND revoked_at IS NULL",
                (now, user_id),
            )
            connection.commit()

    # -- account management ---------------------------------------------------

    def has_login_accounts(self) -> bool:
        with closing(self._connect()) as connection:
            row = connection.execute(
                "SELECT COUNT(*) AS count FROM users WHERE username IS NOT NULL"
            ).fetchone()
        return int(row["count"]) > 0

    def create_account(
        self,
        username: str,
        password: str,
        display_name: str,
        role: str = ROLE_USER,
    ) -> Dict[str, Any]:
        """Create a loginable account with empty fixed lists.

        The row gets an ``login:<username>`` subject so it can never collide
        with ``legacy-local``; fixed lists are seeded through the same path a
        new repository principal uses, never copied from another user.
        """
        normalized = normalize_username(username)
        if not normalized or len(normalized) > 64:
            raise AccountError("username is required")
        if role not in ROLES:
            raise AccountError("role must be admin or user")
        validate_password_strength(password)
        display = str(display_name or "").strip() or normalized
        now = utc_now()
        with closing(self._connect()) as connection:
            existing = connection.execute(
                "SELECT id FROM users WHERE username = ?", (normalized,)
            ).fetchone()
            if existing is not None:
                raise AccountError("username already exists")
            cursor = connection.execute(
                """INSERT INTO users
                       (subject, display_name, status, created_at, updated_at,
                        username, password_hash, role, password_changed_at)
                   VALUES (?, ?, 'active', ?, ?, ?, ?, ?, ?)""",
                (
                    f"login:{normalized}",
                    display,
                    now,
                    now,
                    normalized,
                    hash_password(password),
                    role,
                    now,
                ),
            )
            user_id = int(cursor.lastrowid)
            connection.executemany(
                """INSERT INTO system_lists
                       (user_id, slug, name, name_key, position, is_fixed)
                   VALUES (?, ?, ?, lower(?), ?, 1)""",
                (
                    (user_id, slug, name, name, position)
                    for slug, name, position in FIXED_LISTS
                ),
            )
            connection.commit()
        return {
            "id": user_id,
            "username": normalized,
            "display_name": display,
            "role": role,
            "status": "active",
        }

    def accounts(self) -> List[Dict[str, Any]]:
        """List loginable accounts; never includes password hashes."""
        with closing(self._connect()) as connection:
            rows = connection.execute(
                """SELECT id, username, display_name, role, status,
                          created_at, password_changed_at
                   FROM users WHERE username IS NOT NULL ORDER BY id"""
            ).fetchall()
        return [
            {
                "id": int(row["id"]),
                "username": str(row["username"]),
                "display_name": str(row["display_name"]),
                "role": str(row["role"]),
                "status": str(row["status"]),
                "created_at": str(row["created_at"]),
                "password_changed_at": (
                    str(row["password_changed_at"])
                    if row["password_changed_at"] else None
                ),
            }
            for row in rows
        ]

    def change_password(
        self,
        user_id: int,
        current_password: str,
        new_password: str,
    ) -> None:
        """Rotate a password and revoke every session of that user."""
        with closing(self._connect()) as connection:
            row = connection.execute(
                "SELECT password_hash FROM users WHERE id = ?", (user_id,)
            ).fetchone()
        if row is None:
            raise AccountError("user not found")
        if not verify_password(str(row["password_hash"] or ""), current_password):
            raise AccountError("current password is incorrect")
        validate_password_strength(new_password)
        now = utc_now()
        with closing(self._connect()) as connection:
            connection.execute(
                """UPDATE users
                   SET password_hash = ?, password_changed_at = ?, updated_at = ?
                   WHERE id = ?""",
                (hash_password(new_password), now, now, user_id),
            )
            connection.commit()
        self.revoke_user_sessions(user_id)

    def set_account_status(
        self,
        actor_user_id: int,
        username: str,
        status: str,
    ) -> Dict[str, Any]:
        """Admin maintenance: enable/disable another account."""
        if status not in ACCOUNT_STATUSES:
            raise AccountError("status must be active or disabled")
        normalized = normalize_username(username)
        with closing(self._connect()) as connection:
            row = connection.execute(
                "SELECT id, username FROM users WHERE username = ?",
                (normalized,),
            ).fetchone()
            if row is None:
                raise AccountError("user not found")
            if int(row["id"]) == int(actor_user_id):
                raise AccountError("cannot change your own account status")
            connection.execute(
                "UPDATE users SET status = ?, updated_at = ? WHERE id = ?",
                (status, utc_now(), int(row["id"])),
            )
            connection.commit()
        return {"username": normalized, "status": status}

    # -- provisioning primitives ----------------------------------------------

    def ensure_initial_admin(self) -> str:
        """Create the first administrator from INITIAL_ADMIN_* env vars.

        Runs only while the database has no loginable account at all; the
        legacy row never receives these credentials and legacy holdings are
        not attached.  Returns ``"exists"``, ``"created"``, or
        ``"missing-credentials"``; the last keeps the legacy local mode
        (no login wall) and logs a clear warning so operators know login
        is not yet active.
        """
        if self.has_login_accounts():
            return "exists"
        username = os.environ.get("INITIAL_ADMIN_USERNAME", "").strip()
        password = os.environ.get("INITIAL_ADMIN_PASSWORD", "")
        if not username or not password:
            LOGGER.warning(
                "No login accounts exist and INITIAL_ADMIN_USERNAME / "
                "INITIAL_ADMIN_PASSWORD are not both set. The app keeps "
                "running in legacy local mode without a login wall (same "
                "convention as an unset WEB_AUTH_TOKEN). Set both variables "
                "and restart to provision the first administrator and "
                "activate session login."
            )
            return "missing-credentials"
        try:
            account = self.create_account(username, password, username, ROLE_ADMIN)
        except AccountError as error:
            # A bad INITIAL_ADMIN_PASSWORD must fail startup loudly instead
            # of leaving the instance permanently locked without explanation.
            raise RuntimeError(
                f"INITIAL_ADMIN account could not be created: {error}"
            ) from error
        LOGGER.info(
            "Created initial administrator account '%s' (id=%d) from "
            "INITIAL_ADMIN_* environment variables",
            account["username"],
            account["id"],
        )
        return "created"

    def ensure_seed_logins(self) -> Dict[str, List[str]]:
        """Idempotently create the private-repo test accounts 1–5.

        Missing usernames are created through ``create_account`` (empty lists,
        never copied from ``legacy-local``). Existing usernames are skipped
        without rotating passwords. Called from ``web.main()`` only so tests
        that construct ``WebApplication`` keep an empty loginable set.
        """
        created: List[str] = []
        skipped: List[str] = []
        for username, password, display_name, role in SEED_LOGINS:
            try:
                self.create_account(username, password, display_name, role)
            except AccountError as error:
                if "already exists" in str(error):
                    skipped.append(username)
                    continue
                raise
            created.append(username)
        if created:
            LOGGER.info(
                "Seeded login accounts: %s",
                ", ".join(created),
            )
        return {"created": created, "skipped": skipped}

    def attach_legacy_login(self, username: str, password: str) -> Dict[str, Any]:
        """Opt-in CLI primitive: make the legacy row loginable.

        Writes ``username`` / ``password_hash`` / ``role=admin`` onto the same
        ``legacy-local`` row so the historical holdings become visible to that
        login.  Refused when the username already belongs to any existing user
        or when the legacy row is already attached.  Never called from the
        default web startup path.
        """
        normalized = normalize_username(username)
        if not normalized or len(normalized) > 64:
            raise AccountError("username is required")
        validate_password_strength(password)
        now = utc_now()
        with closing(self._connect()) as connection:
            existing = connection.execute(
                "SELECT id FROM users WHERE username = ?", (normalized,)
            ).fetchone()
            if existing is not None:
                raise AccountError("username already belongs to an existing user")
            legacy = connection.execute(
                "SELECT id, username FROM users WHERE subject = ?",
                (LEGACY_LOCAL_SUBJECT,),
            ).fetchone()
            if legacy is None:
                raise AccountError("legacy-local user not found")
            if legacy["username"]:
                raise AccountError(
                    "legacy data is already attached to a login account"
                )
            connection.execute(
                """UPDATE users
                   SET username = ?, password_hash = ?, role = 'admin',
                       status = 'active', updated_at = ?, password_changed_at = ?
                   WHERE id = ?""",
                (
                    normalized,
                    hash_password(password),
                    now,
                    now,
                    int(legacy["id"]),
                ),
            )
            connection.commit()
            legacy_id = int(legacy["id"])
        return {"id": legacy_id, "username": normalized, "role": ROLE_ADMIN}
