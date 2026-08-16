"""Fail-closed parser for CEO.ca's public SEDAR bot channel."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime, timezone
from typing import Any, Iterable, List, Mapping, Optional, Sequence
from urllib.parse import urlparse
from zoneinfo import ZoneInfo

TORONTO = ZoneInfo("America/Toronto")
_FILING_RE = re.compile(
    r"^#sedar\s+\$(?P<ticker>[A-Z0-9.\-]+)\s+"
    r"(?P<issuer>.+?)\s+just filed a new SEDAR document:\s*\n+\s*"
    r"(?P<document>[^\n]+?)\s*\n+\s*(?P<url>https://\S+)\s*$",
    re.IGNORECASE,
)
_SAFE_PDF_PATH = re.compile(r"^/content/sedar/[A-Za-z0-9._~%+\-]+\.pdf$")


@dataclass(frozen=True)
class CeocaSedarRow:
    spiel_id: str
    ticker: str
    issuer: str
    document: str
    url: str
    published_at: datetime


def parse_ceoca_sedar_spiels(
    spiels: Sequence[Mapping[str, Any]],
    *,
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
    expected_channel: str = "sedar",
) -> List[CeocaSedarRow]:
    """Parse only exact SEDAR-bot PDF messages and reject lookalikes."""
    rows: List[CeocaSedarRow] = []
    for raw in spiels:
        row = _parse_one(raw, expected_channel=expected_channel)
        if row is None:
            continue
        local_day = row.published_at.astimezone(TORONTO).date()
        if start_date is not None and local_day < start_date:
            continue
        if end_date is not None and local_day > end_date:
            continue
        rows.append(row)
    return _dedupe(rows)


def _parse_one(
    raw: Mapping[str, Any], *, expected_channel: str
) -> Optional[CeocaSedarRow]:
    if (
        str(raw.get("channel") or "").strip().lower()
        != str(expected_channel).strip().lower()
    ):
        return None
    if str(raw.get("name") or "").strip() != "SEDAR bot":
        return None
    if str(raw.get("bot") or "").strip().lower() != "sedi":
        return None
    spiel_id = str(raw.get("spiel_id") or "").strip()
    body = str(raw.get("spiel") or "").strip()
    published = _timestamp_from_ms(raw.get("timestamp"))
    if not spiel_id or published is None:
        return None
    match = _FILING_RE.fullmatch(body)
    if match is None:
        return None
    url = match.group("url").rstrip(".,")
    parsed = urlparse(url)
    if (
        parsed.scheme != "https"
        or parsed.netloc.lower() != "ceo.ca"
        or parsed.query
        or parsed.fragment
        or _SAFE_PDF_PATH.fullmatch(parsed.path) is None
    ):
        return None
    return CeocaSedarRow(
        spiel_id=spiel_id,
        ticker=match.group("ticker").upper(),
        issuer=" ".join(match.group("issuer").split()),
        document=" ".join(match.group("document").split()),
        url=url,
        published_at=published,
    )


def _timestamp_from_ms(raw: Any) -> Optional[datetime]:
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return None
    if value <= 0:
        return None
    return datetime.fromtimestamp(value / 1000.0, tz=timezone.utc)


def _dedupe(rows: Iterable[CeocaSedarRow]) -> List[CeocaSedarRow]:
    seen: set[str] = set()
    unique: List[CeocaSedarRow] = []
    for row in rows:
        if row.spiel_id in seen:
            continue
        seen.add(row.spiel_id)
        unique.append(row)
    return unique
