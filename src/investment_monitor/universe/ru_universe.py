# -*- coding: utf-8 -*-
"""Russia (RU) read-only tradeable universe from MOEX ISS (P5-0).

Source (live verified 2026-08-16): the key-free official MOEX ISS JSON
endpoint ``/iss/engines/stock/markets/shares/boards/TQBR/securities.json``
(505 rows on TQBR, 770 rows across the shares market).

IBKR cannot open or close MOEX positions at this time and does not receive
MOEX pricing, so this universe is **read-only research data**:
``trading_status`` is always ``"unavailable"`` and the payload never flows
into information_items / the daily feed. It only backfills name / ISIN /
board for RU symbols in the catalog and coverage board.
"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Mapping, Optional
from urllib.request import Request, urlopen

LOGGER = logging.getLogger(__name__)

DEFAULT_CACHE_PATH = ".cache/investment_monitor/ru_universe.json"
DEFAULT_BASE_URL = "https://iss.moex.com/iss"
TQBR_PATH = (
    "/engines/stock/markets/shares/boards/TQBR/securities.json?iss.meta=off"
)
DEFAULT_USER_AGENT = "InvestmentMonitor/0.1 (internal workspace)"


class RuUniverseError(RuntimeError):
    """Raised when the read-only MOEX universe cannot be refreshed."""


def load_ru_universe(
    path: Optional[Path] = None,
) -> Optional[Mapping[str, Any]]:
    """Load the cached RU universe payload, or None when absent/invalid."""
    cache_path = _cache_path(path)
    try:
        with cache_path.open("r", encoding="utf-8") as cache_file:
            return json.load(cache_file)
    except (OSError, json.JSONDecodeError):
        return None


def refresh_ru_universe(
    *,
    path: Optional[Path] = None,
    opener: Optional[Callable[..., Any]] = None,
    base_url: Optional[str] = None,
    refreshed_at: Optional[str] = None,
) -> Mapping[str, Any]:
    """Refresh the read-only RU universe from MOEX ISS TQBR shares."""
    cache_path = _cache_path(path)
    resolved_base = (
        base_url
        or os.environ.get("RU_UNIVERSE_BASE_URL", DEFAULT_BASE_URL)
    ).rstrip("/")
    url = resolved_base + TQBR_PATH
    try:
        payload = _get_json(url, opener or urlopen)
    except Exception as error:  # noqa: BLE001 - 调用方收编
        LOGGER.warning("ru_universe source=moex_iss failed: %s", error)
        raise RuUniverseError(f"MOEX ISS TQBR failed: {error}") from error

    securities = payload.get("securities") or {}
    columns = [str(c) for c in securities.get("columns") or []]
    rows = securities.get("data") or []
    entries: Dict[str, Dict[str, Any]] = {}
    for row in rows:
        record = dict(zip(columns, row))
        secid = str(record.get("SECID") or "").strip().upper()
        if not secid:
            continue
        entries[secid] = {
            "ticker": secid,
            "name": str(record.get("SECNAME") or record.get("LATNAME") or secid),
            "isin": str(record.get("ISIN") or "").strip().upper(),
            "board": str(record.get("BOARDID") or "TQBR"),
            "currency": str(record.get("CURRENCYID") or ""),
            "status": str(record.get("STATUS") or ""),
            "instrument_type": "stock",
        }

    if not entries:
        raise RuUniverseError(
            "MOEX ISS TQBR returned no parseable share entries."
        )

    payload_out = {
        "updated_at": refreshed_at or datetime.now(timezone.utc).isoformat(),
        "source": ["moex_iss"],
        "source_tier": "official",
        "trading_status": "unavailable",
        "readonly": True,
        "counts": {"tqbr": len(entries)},
        "items": sorted(
            entries.values(), key=lambda item: item["ticker"]
        ),
    }
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = cache_path.with_suffix(cache_path.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8") as handle:
        json.dump(payload_out, handle, ensure_ascii=False)
    temporary.replace(cache_path)
    return payload_out


def ru_universe_name_map(
    path: Optional[Path] = None,
) -> Mapping[str, Mapping[str, str]]:
    """Return normalized ticker -> {name, exchange, board, isin}."""
    payload = load_ru_universe(path)
    if not payload:
        return {}
    result: Dict[str, Mapping[str, str]] = {}
    for item in payload.get("items") or []:
        ticker = str(item.get("ticker") or "").strip().upper()
        if not ticker:
            continue
        board = str(item.get("board") or "TQBR")
        result[ticker] = {
            "name": str(item.get("name") or ticker),
            "exchange": "MOEX",
            "board": board,
            "isin": str(item.get("isin") or ""),
        }
    return result


def search_ru_universe(
    query: str,
    path: Optional[Path] = None,
) -> List[Mapping[str, Any]]:
    """Search the read-only RU cache by ticker, name, ISIN or board."""
    payload = load_ru_universe(path)
    if not payload:
        return []
    needle = str(query or "").strip().lower()
    if not needle:
        return []
    matches: List[Mapping[str, Any]] = []
    for item in payload.get("items") or []:
        haystack = (
            f"{item.get('ticker') or ''} "
            f"{item.get('name') or ''} "
            f"{item.get('isin') or ''} "
            f"{item.get('board') or ''}"
        ).lower()
        if needle in haystack:
            matches.append(dict(item))
        if len(matches) >= 50:
            break
    return matches


def _get_json(url: str, opener: Callable[..., Any]) -> Mapping[str, Any]:
    request = Request(
        url,
        headers={
            "User-Agent": DEFAULT_USER_AGENT,
            "Accept": "application/json",
        },
    )
    with opener(request, timeout=20) as response:
        raw = response.read()
    return json.loads(raw.decode("utf-8"))


def _cache_path(path: Optional[Path]) -> Path:
    return Path(
        path or os.environ.get("RU_UNIVERSE_CACHE_PATH", DEFAULT_CACHE_PATH)
    )


__all__ = [
    "RuUniverseError",
    "load_ru_universe",
    "refresh_ru_universe",
    "ru_universe_name_map",
    "search_ru_universe",
]
