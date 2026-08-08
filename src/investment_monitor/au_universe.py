"""AU tradeable universe cache (breadth only) from the ASX company directory.

Source (live verified 2026-08-08): the ASX site research API company
directory (``asx.api.markitdigital.com/asx-research/1.0/companies/directory``,
~1840 listed companies; the same endpoint family as the AU-1 announcements
connector). Key-free JSON with ``itemsPerPage``/``page`` pagination. The
comparable ``.../directory/file`` CSV is the same source in CSV form. The
cache is breadth only and never flows into information_items / Today feed.
"""

from __future__ import annotations

import json
import logging
import os
import ssl
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Mapping, Optional
from urllib.request import HTTPSHandler, Request, build_opener, urlopen

from .web_repository import normalize_au_ticker

LOGGER = logging.getLogger(__name__)

DEFAULT_CACHE_PATH = ".cache/investment_monitor/au_universe.json"
DIRECTORY_URL = (
    "https://asx.api.markitdigital.com/asx-research/1.0/companies/directory"
)
DIRECTORY_URL_ENV = "AU_UNIVERSE_DIRECTORY_URL"
DEFAULT_USER_AGENT = "InvestmentMonitor/0.1 (internal workspace)"
PAGE_SIZE = 1000
MAX_PAGES = 20


class AuUniverseError(RuntimeError):
    """Raised when the AU universe cannot be refreshed at all."""


def load_au_universe(
    path: Optional[Path] = None,
) -> Optional[Mapping[str, Any]]:
    """Load the cached universe payload, or None when absent/invalid."""
    cache_path = _cache_path(path)
    try:
        with cache_path.open("r", encoding="utf-8") as cache_file:
            return json.load(cache_file)
    except (OSError, json.JSONDecodeError):
        return None


def refresh_au_universe(
    *,
    path: Optional[Path] = None,
    opener: Optional[Callable[..., Any]] = None,
    url: Optional[str] = None,
    refreshed_at: Optional[str] = None,
) -> Mapping[str, Any]:
    """Refresh the AU universe from the ASX company directory.

    The directory is paginated (``itemsPerPage`` + ``page``) until the
    response ``count`` is reached or a short/empty page ends the loop.
    A full failure raises ``AuUniverseError``; the cache is written
    atomically (tmp + replace).
    """
    cache_path = _cache_path(path)
    verify_ssl = (
        os.environ.get("AU_UNIVERSE_VERIFY_SSL", "true")
        .strip()
        .lower()
    ) not in {"0", "false", "no", "off"}
    default_opener = _make_opener(verify_ssl)
    directory_url = url or os.environ.get(DIRECTORY_URL_ENV, DIRECTORY_URL)

    try:
        rows = _fetch_directory_rows(
            directory_url,
            opener or default_opener,
        )
    except Exception as error:
        LOGGER.warning(
            "au_universe source=asx_directory failed: %s",
            error,
        )
        raise AuUniverseError(
            f"ASX company directory failed: {error}"
        ) from error
    entries: Dict[str, Mapping[str, Any]] = {}
    for row in rows:
        ticker = str(row.get("ticker") or "")
        if not ticker or ticker in entries:
            continue
        entries[ticker] = {
            "ticker": ticker,
            "name": str(row.get("name") or ticker),
            "industry": str(row.get("industry") or ""),
            "board": "ASX",
            "exchange": "ASX",
            "status": "active",
        }

    if not entries:
        raise AuUniverseError(
            "AU universe source failed; no entries available."
        )

    payload = {
        "updated_at": (
            refreshed_at
            or datetime.now(timezone.utc).isoformat()
        ),
        "source": ["asx_directory"],
        "counts": {"ASX": len(entries)},
        "items": sorted(
            entries.values(),
            key=lambda item: item["ticker"],
        ),
    }
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = cache_path.with_suffix(cache_path.suffix + ".tmp")
    with temporary_path.open("w", encoding="utf-8") as cache_file:
        json.dump(payload, cache_file, ensure_ascii=False)
    temporary_path.replace(cache_path)
    return payload


def au_universe_name_map(
    path: Optional[Path] = None,
) -> Mapping[str, Mapping[str, str]]:
    """Return normalized ticker -> {name, exchange} for web fallback."""
    payload = load_au_universe(path)
    if not payload:
        return {}
    result: Dict[str, Mapping[str, str]] = {}
    for item in payload.get("items") or []:
        ticker = str(item.get("ticker") or "").strip()
        if not ticker:
            continue
        result[ticker] = {
            "name": str(item.get("name") or ticker),
            "exchange": str(item.get("board") or "ASX"),
        }
    return result


def search_au_universe(
    query: str,
    path: Optional[Path] = None,
) -> List[Mapping[str, Any]]:
    """Search the cached AU universe by ticker or name substring."""
    payload = load_au_universe(path)
    if not payload:
        return []
    needle = str(query or "").strip().lower()
    if not needle:
        return []
    matches: List[Mapping[str, Any]] = []
    for item in payload.get("items") or []:
        haystack = (
            f"{item.get('ticker') or ''} "
            f"{item.get('name') or ''}"
        ).lower()
        if needle in haystack:
            matches.append(dict(item))
        if len(matches) >= 50:
            break
    return matches


def _fetch_directory_rows(
    url: str,
    opener: Callable[..., Any],
) -> List[Mapping[str, Any]]:
    items: List[Mapping[str, Any]] = []
    for page in range(MAX_PAGES):
        page_url = f"{url}?itemsPerPage={PAGE_SIZE}&page={page}"
        payload = _get_json(page_url, opener)
        if not isinstance(payload, dict):
            raise AuUniverseError(
                "ASX directory response was not a JSON object."
            )
        data = payload.get("data")
        if not isinstance(data, dict):
            raise AuUniverseError(
                "ASX directory response had no data object."
            )
        page_items = data.get("items")
        if not isinstance(page_items, list):
            raise AuUniverseError(
                "ASX directory response had no items list."
            )
        items.extend(
            row
            for row in page_items
            if isinstance(row, dict)
        )
        count = _as_int(data.get("count"))
        if len(page_items) < PAGE_SIZE or (
            count is not None and len(items) >= count
        ):
            break
    records: List[Mapping[str, Any]] = []
    seen: set = set()
    for item in items:
        symbol = str(item.get("symbol") or "").strip()
        name = str(item.get("displayName") or "").strip()
        ticker = normalize_au_ticker(symbol)
        if not ticker or not name or ticker in seen:
            continue
        seen.add(ticker)
        records.append(
            {
                "ticker": ticker,
                "name": name,
                "industry": str(item.get("industry") or "").strip(),
            }
        )
    if not records:
        raise AuUniverseError(
            "ASX directory returned no parseable entries."
        )
    return records


def _as_int(value: Any) -> Optional[int]:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _get_json(
    url: str,
    opener: Callable[..., Any],
) -> Any:
    request = Request(
        url,
        headers={
            "User-Agent": DEFAULT_USER_AGENT,
            "Accept": "application/json",
            "Accept-Language": "en-AU,en;q=0.9",
        },
        method="GET",
    )
    with opener(request, timeout=60) as response:
        raw = response.read()
    return json.loads(raw.decode("utf-8", errors="replace"))


def _make_opener(verify_ssl: bool) -> Callable[..., Any]:
    if verify_ssl:
        return urlopen
    return build_opener(
        HTTPSHandler(context=ssl._create_unverified_context())
    ).open


def _cache_path(path: Optional[Path]) -> Path:
    return Path(
        path or os.environ.get("AU_UNIVERSE_CACHE_PATH", DEFAULT_CACHE_PATH)
    )
