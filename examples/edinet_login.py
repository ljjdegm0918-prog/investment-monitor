"""Minimal login-path integration for an application's existing user model."""

from datetime import datetime, timedelta, timezone
from typing import Any

from investment_monitor.sources.edinet import EDINETConnector


def on_login(user: Any, connector: EDINETConnector):
    """Return the user's official EDINET disclosures from the last 24 hours."""
    now = datetime.now(timezone.utc)
    return connector.getWatchlistDisclosuresSince(
        companies=user.watchlist,
        since=now - timedelta(hours=24),
        now=now,
        include_downloads=False,
    )