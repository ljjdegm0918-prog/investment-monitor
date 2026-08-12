"""Parse CEO.ca spiel JSON for Toronto calendar-day filtering."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date, datetime, timezone
from typing import Any, Iterable, List, Mapping, Optional, Sequence
from zoneinfo import ZoneInfo

TORONTO = ZoneInfo("America/Toronto")
MAX_TITLE_LEN = 200
MAX_SUMMARY_LEN = 500


@dataclass(frozen=True)
class CeocaSpielRow:
    """One CEO.ca channel spiel."""

    spiel_id: str
    body: str
    author: str
    channel: str
    published_at: datetime


def parse_ceoca_spiel_payload(
    payload: Mapping[str, Any] | str,
    *,
    on_date: date,
) -> List[CeocaSpielRow]:
    """Parse a CEO.ca ``get_spiels`` JSON payload and filter to ``on_date``.

    ``payload`` may be a decoded mapping or a JSON string (fixture file).
    """
    data = _coerce_payload(payload)
    spiels = data.get("spiels")
    if not isinstance(spiels, list):
        return []
    return filter_spiels_to_toronto_day(spiels, on_date=on_date)


def filter_spiels_to_toronto_day(
    spiels: Sequence[Mapping[str, Any]],
    *,
    on_date: date,
) -> List[CeocaSpielRow]:
    """Return spiel rows whose Toronto calendar day equals ``on_date``."""
    rows: List[CeocaSpielRow] = []
    for raw in spiels:
        row = _row_from_spiel(raw)
        if row is None:
            continue
        if row.published_at.astimezone(TORONTO).date() != on_date:
            continue
        rows.append(row)
    return _dedupe_by_spiel_id(rows)


def spiel_title(body: str, *, author: str = "") -> str:
    """Build a display title from spiel body and optional author handle."""
    text = " ".join(str(body or "").split())
    if not text:
        text = "CEO.ca post"
    if author:
        prefix = str(author).strip()
        if prefix and not text.lower().startswith(prefix.lower()):
            text = f"{prefix}: {text}"
    if len(text) > MAX_TITLE_LEN:
        text = text[: MAX_TITLE_LEN - 1].rstrip() + "…"
    return text


def toronto_day(moment: datetime) -> date:
    """Calendar day in America/Toronto for day filtering."""
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment.astimezone(TORONTO).date()


def toronto_day_from_ms(timestamp_ms: Any) -> Optional[date]:
    """Convert CEO.ca millisecond epoch to a Toronto calendar day."""
    published = _timestamp_from_ms(timestamp_ms)
    if published is None:
        return None
    return toronto_day(published)


def _coerce_payload(payload: Mapping[str, Any] | str) -> Mapping[str, Any]:
    if isinstance(payload, str):
        decoded = json.loads(payload)
        if not isinstance(decoded, Mapping):
            raise ValueError("CEO.ca payload must be a JSON object.")
        return decoded
    return payload


def _row_from_spiel(raw: Mapping[str, Any]) -> Optional[CeocaSpielRow]:
    spiel_id = str(raw.get("spiel_id") or "").strip()
    if not spiel_id:
        return None
    published = _timestamp_from_ms(raw.get("timestamp"))
    if published is None:
        return None
    channel = str(raw.get("channel") or "").strip().lower()
    body = str(raw.get("spiel") or "").strip()
    author = str(raw.get("name") or "").strip()
    return CeocaSpielRow(
        spiel_id=spiel_id,
        body=body,
        author=author,
        channel=channel,
        published_at=published,
    )


def _timestamp_from_ms(raw: Any) -> Optional[datetime]:
    try:
        ms = int(raw)
    except (TypeError, ValueError):
        return None
    if ms <= 0:
        return None
    return datetime.fromtimestamp(ms / 1000.0, tz=timezone.utc)


def _dedupe_by_spiel_id(rows: Iterable[CeocaSpielRow]) -> List[CeocaSpielRow]:
    seen: set[str] = set()
    unique: List[CeocaSpielRow] = []
    for row in rows:
        if row.spiel_id in seen:
            continue
        seen.add(row.spiel_id)
        unique.append(row)
    return unique
