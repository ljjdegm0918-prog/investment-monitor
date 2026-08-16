# -*- coding: utf-8 -*-
"""US tradeable universe cache (breadth only) from the SEC ticker file.

Source (live verified 2026-08-16): the key-free official SEC JSON
``https://www.sec.gov/files/company_tickers_exchange.json`` with a
mandatory User-Agent header. It covers SEC-registered companies with
``cik/name/ticker/exchange`` (~10k rows in the non-exchange file).

This is breadth-only identity data, not a complete exchange directory:
SEC registration is the boundary. The cache is used for name/exchange
backfill and the coverage board; it never flows into information_items.
"""

from __future__ import annotations

import gzip
import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Mapping, Optional
from urllib.request import Request, urlopen

LOGGER = logging.getLogger(__name__)

DEFAULT_CACHE_PATH = ".cache/investment_monitor/us_universe.json"
DEFAULT_URL = "https://www.sec.gov/files/company_tickers_exchange.json"
DEFAULT_USER_AGENT = "InvestmentMonitor research@example.com"


class UsUniverseError(RuntimeError):
    """Raised when the SEC ticker universe cannot be refreshed."""


def load_us_universe(
    path: Optional[Path] = None,
) -> Optional[Mapping[str, Any]]:
    """Load the cached US universe payload, or None when absent/invalid."""
    cache_path = _cache_path(path)
    try:
        with cache_path.open("r", encoding="utf-8") as cache_file:
            return json.load(cache_file)
    except (OSError, json.JSONDecodeError):
        return None


def refresh_us_universe(
    *,
    path: Optional[Path] = None,
    opener: Optional[Callable[..., Any]] = None,
    url: Optional[str] = None,
    refreshed_at: Optional[str] = None,
) -> Mapping[str, Any]:
    """Refresh the US universe from the SEC ticker exchange JSON."""
    cache_path = _cache_path(path)
    source_url = url or os.environ.get("US_UNIVERSE_URL", DEFAULT_URL)
    request = Request(
        source_url,
        headers={
            "User-Agent": os.environ.get(
                "US_UNIVERSE_USER_AGENT", DEFAULT_USER_AGENT
            ),
            "Accept": "application/json",
        },
    )
    try:
        with (opener or urlopen)(request, timeout=20) as response:
            raw = response.read()
            if response.headers.get("Content-Encoding") == "gzip":
                raw = gzip.decompress(raw)
            payload = json.loads(raw.decode("utf-8"))
    except Exception as error:  # noqa: BLE001 - 调用方收编
        LOGGER.warning("us_universe source=sec_tickers failed: %s", error)
        raise UsUniverseError(f"SEC ticker universe failed: {error}") from error

    fields = list(payload.get("fields") or [])
    rows = payload.get("data") or []
    entries: Dict[str, Dict[str, Any]] = {}
    for row in rows:
        record = dict(zip(fields, row))
        ticker = str(record.get("ticker") or "").strip().upper()
        if not ticker:
            continue
        entries[ticker] = {
            "ticker": ticker,
            "name": str(record.get("name") or ticker),
            "exchange": str(record.get("exchange") or "SEC"),
            "cik": str(record.get("cik") or ""),
            "instrument_type": "stock",
        }

    if not entries:
        raise UsUniverseError("SEC ticker universe returned no entries.")

    payload_out = {
        "updated_at": refreshed_at or datetime.now(timezone.utc).isoformat(),
        "source": ["sec_company_tickers_exchange"],
        "source_tier": "official",
        "counts": {"companies": len(entries)},
        "items": sorted(entries.values(), key=lambda item: item["ticker"]),
    }
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = cache_path.with_suffix(cache_path.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8") as handle:
        json.dump(payload_out, handle, ensure_ascii=False)
    temporary.replace(cache_path)
    return payload_out


def us_universe_name_map(
    path: Optional[Path] = None,
) -> Mapping[str, Mapping[str, str]]:
    """Return normalized ticker -> {name, exchange, cik}."""
    payload = load_us_universe(path)
    if not payload:
        return {}
    result: Dict[str, Mapping[str, str]] = {}
    for item in payload.get("items") or []:
        ticker = str(item.get("ticker") or "").strip().upper()
        if not ticker:
            continue
        result[ticker] = {
            "name": str(item.get("name") or ticker),
            "exchange": str(item.get("exchange") or "SEC"),
            "cik": str(item.get("cik") or ""),
        }
    return result


def search_us_universe(
    query: str,
    path: Optional[Path] = None,
) -> List[Mapping[str, Any]]:
    """Search the cached US universe by ticker, name, exchange or CIK."""
    payload = load_us_universe(path)
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
            f"{item.get('exchange') or ''} "
            f"{item.get('cik') or ''}"
        ).lower()
        if needle in haystack:
            matches.append(dict(item))
        if len(matches) >= 50:
            break
    return matches


def _cache_path(path: Optional[Path]) -> Path:
    return Path(
        path or os.environ.get("US_UNIVERSE_CACHE_PATH", DEFAULT_CACHE_PATH)
    )


__all__ = [
    "UsUniverseError",
    "load_us_universe",
    "refresh_us_universe",
    "search_us_universe",
    "us_universe_name_map",
]
