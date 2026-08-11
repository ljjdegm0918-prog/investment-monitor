"""DE tradeable universe cache (breadth only) from the Xetra all-instruments CSV.

Source (live verified 2026-08-10): the key-free Deutsche Boerse Cash Market
``t7-xetr-allTradableInstruments.csv`` download (blob URL published on the
Xetra / cash-market Downloads page). Semicolon-delimited; two metadata rows,
then a header row, then Active/Active instrument rows. We keep Instrument
Type ``CS`` (common shares) with a non-empty Mnemonic on MIC ``XETR``.

Board labels come from ``Product Assignment Group Description`` (e.g. DAX,
MDAX, SDAX, Scale, …) — coverage is whatever Xetra publishes that day, not a
hand-maintained DAX-40 list. The cache never flows into information_items /
Daily feed; it only backfills name / exchange / ISIN on add-company and for
EQS ISIN matching.
"""

from __future__ import annotations

import csv
import io
import json
import logging
import os
import ssl
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Mapping, Optional
from urllib.request import HTTPSHandler, Request, build_opener, urlopen

from ..web_repository import normalize_de_ticker

LOGGER = logging.getLogger(__name__)

DEFAULT_CACHE_PATH = ".cache/investment_monitor/de_universe.json"
DIRECTORY_URL = (
    "https://www.cashmarket.deutsche-boerse.com/resource/blob/1528/"
    "a31c10e3183f4c5dd721f9c7f9eaaaea/data/t7-xetr-allTradableInstruments.csv"
)
DIRECTORY_URL_ENV = "DE_UNIVERSE_DIRECTORY_URL"
DEFAULT_USER_AGENT = "InvestmentMonitor/0.1 (internal workspace)"


class DeUniverseError(RuntimeError):
    """Raised when the DE universe cannot be refreshed at all."""


def load_de_universe(
    path: Optional[Path] = None,
) -> Optional[Mapping[str, Any]]:
    """Load the cached universe payload, or None when absent/invalid."""
    cache_path = _cache_path(path)
    try:
        with cache_path.open("r", encoding="utf-8") as cache_file:
            return json.load(cache_file)
    except (OSError, json.JSONDecodeError):
        return None


def refresh_de_universe(
    *,
    path: Optional[Path] = None,
    opener: Optional[Callable[..., Any]] = None,
    url: Optional[str] = None,
    refreshed_at: Optional[str] = None,
) -> Mapping[str, Any]:
    """Refresh the DE universe from the Xetra all-tradable-instruments CSV."""
    cache_path = _cache_path(path)
    verify_ssl = (
        os.environ.get("DE_UNIVERSE_VERIFY_SSL", "true")
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
            "de_universe source=xetra_all_tradable_csv failed: %s",
            error,
        )
        raise DeUniverseError(
            f"Xetra tradable instruments CSV failed: {error}"
        ) from error

    entries: Dict[str, Mapping[str, Any]] = {}
    counts: Dict[str, int] = {}
    for row in rows:
        ticker = str(row.get("ticker") or "")
        if not ticker or ticker in entries:
            continue
        board = str(row.get("board") or "Xetra")
        entries[ticker] = {
            "ticker": ticker,
            "name": str(row.get("name") or ticker),
            "isin": str(row.get("isin") or ""),
            "board": board,
            "exchange": board,
            "status": "active",
        }
        counts[board] = counts.get(board, 0) + 1

    if not entries:
        raise DeUniverseError(
            "DE universe source failed; no Xetra equity entries available."
        )

    payload = {
        "updated_at": (
            refreshed_at
            or datetime.now(timezone.utc).isoformat()
        ),
        "source": ["xetra_all_tradable_csv"],
        "counts": counts,
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


def de_universe_name_map(
    path: Optional[Path] = None,
) -> Mapping[str, Mapping[str, str]]:
    """Return normalized ticker -> {name, exchange, board, isin}."""
    payload = load_de_universe(path)
    if not payload:
        return {}
    result: Dict[str, Mapping[str, str]] = {}
    for item in payload.get("items") or []:
        ticker = str(item.get("ticker") or "").strip()
        if not ticker:
            continue
        board = str(item.get("board") or item.get("exchange") or "Xetra")
        result[ticker] = {
            "name": str(item.get("name") or ticker),
            "exchange": board,
            "board": board,
            "isin": str(item.get("isin") or ""),
        }
    return result


def search_de_universe(
    query: str,
    path: Optional[Path] = None,
) -> List[Mapping[str, Any]]:
    """Search the cached DE universe by ticker, name, ISIN or board."""
    payload = load_de_universe(path)
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


def _fetch_directory_rows(
    url: str,
    opener: Callable[..., Any],
) -> List[Mapping[str, Any]]:
    raw = _get_csv(url, opener)
    reader = csv.reader(io.StringIO(raw), delimiter=";")
    records: List[Mapping[str, Any]] = []
    seen_header = False
    for row in reader:
        if not row:
            continue
        if not seen_header:
            if str(row[0]).strip() == "Product Status" and len(row) > 18:
                seen_header = True
            continue
        if len(row) <= 18:
            continue
        if row[0].strip() != "Active" or row[1].strip() != "Active":
            continue
        if row[8].strip().upper() != "XETR":
            continue
        if row[18].strip().upper() != "CS":
            continue
        mnemonic = str(row[7]).strip()
        if not mnemonic or mnemonic == "-":
            continue
        ticker = normalize_de_ticker(mnemonic)
        if not ticker:
            continue
        board = str(row[12]).strip() or str(row[11]).strip() or "Xetra"
        records.append(
            {
                "ticker": ticker,
                "name": str(row[2]).strip(),
                "isin": str(row[3]).strip().upper(),
                "board": board,
            }
        )
    if not records:
        raise DeUniverseError(
            "Xetra CSV returned no parseable equity (CS) entries."
        )
    return records


def _get_csv(url: str, opener: Callable[..., Any]) -> str:
    request = Request(
        url,
        headers={
            "User-Agent": DEFAULT_USER_AGENT,
            "Accept": "text/csv,*/*",
            "Accept-Language": "en,de;q=0.8",
        },
        method="GET",
    )
    with opener(request, timeout=90) as response:
        raw = response.read()
    return raw.decode("utf-8-sig", errors="replace")


def _make_opener(verify_ssl: bool) -> Callable[..., Any]:
    if verify_ssl:
        return urlopen
    return build_opener(
        HTTPSHandler(context=ssl._create_unverified_context())
    ).open


def _cache_path(path: Optional[Path]) -> Path:
    return Path(
        path or os.environ.get("DE_UNIVERSE_CACHE_PATH", DEFAULT_CACHE_PATH)
    )
