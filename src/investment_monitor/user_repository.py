"""Stable user-identity primitives shared by multi-user repositories.

This module deliberately does not contain authentication or passwords.  A later
authentication layer maps a verified session to one of these durable IDs.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone

LEGACY_LOCAL_SUBJECT = "legacy-local"
LEGACY_LOCAL_DISPLAY_NAME = "Local user"


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def ensure_legacy_local_user(connection: sqlite3.Connection) -> int:
    """Return the deterministic owner for all pre-authentication local data."""
    now = utc_now()
    connection.execute(
        """
        INSERT OR IGNORE INTO users
            (subject, display_name, status, created_at, updated_at)
        VALUES (?, ?, 'legacy', ?, ?)
        """,
        (LEGACY_LOCAL_SUBJECT, LEGACY_LOCAL_DISPLAY_NAME, now, now),
    )
    row = connection.execute(
        "SELECT id FROM users WHERE subject = ?", (LEGACY_LOCAL_SUBJECT,)
    ).fetchone()
    if row is None:
        raise RuntimeError("legacy-local user was not created")
    return int(row[0])
