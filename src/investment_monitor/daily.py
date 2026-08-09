"""User-local calendar-day helpers shared by Today, badges and the feed.

Day boundaries are computed in the requesting user's IANA timezone, not a
hard-coded Eastern zone. Date-only disclosures (DART rcept_dt, Companies
House filing date, HKEX DI notice date) are aligned by their disclosure
``calendar_date`` metadata instead of being converted through UTC midnight,
which used to drop them into the previous day for some users.
"""

from __future__ import annotations

import logging
from datetime import date, datetime, time, timedelta, timezone
from typing import Optional, Tuple
from zoneinfo import ZoneInfo

LOGGER = logging.getLogger(__name__)

# Browser-detection fallback and backend default for missing/invalid zones.
DEFAULT_USER_ZONE = "America/New_York"


def resolve_timezone(value: Optional[str]) -> ZoneInfo:
    """Resolve a user IANA zone; unknown values fall back safely."""
    if not value:
        return ZoneInfo(DEFAULT_USER_ZONE)
    try:
        return ZoneInfo(value)
    except Exception:
        LOGGER.warning(
            "Unknown or invalid timezone %r; falling back to %s",
            value,
            DEFAULT_USER_ZONE,
        )
        return ZoneInfo(DEFAULT_USER_ZONE)


def local_day_bounds(
    day: date,
    zone: ZoneInfo,
) -> Tuple[datetime, datetime]:
    """Return (start_utc, end_utc) for one calendar day in ``zone``."""
    start_local = datetime.combine(day, time.min, tzinfo=zone)
    next_day = day + timedelta(days=1)
    end_local = datetime.combine(next_day, time.min, tzinfo=zone)
    return (
        start_local.astimezone(timezone.utc),
        end_local.astimezone(timezone.utc),
    )


def date_only_market_noon(
    calendar_day: date,
    zone: ZoneInfo,
) -> datetime:
    """Convert a date-only disclosure to market-local noon in UTC.

    The noon anchor keeps display sane across most zones, but Today grouping
    always prefers ``calendar_date`` alignment over this timestamp.
    """
    return datetime.combine(
        calendar_day,
        time(hour=12),
        tzinfo=zone,
    ).astimezone(timezone.utc)
