# -*- coding: utf-8 -*-
"""Shared Euronext live CSV download/parse helpers for NL/FR/BE/NO/PT.

The key-free Euronext live all-stocks CSV
(``live.euronext.com/en/pd_es/data/stocks/download?mics=dm_all_stock``)
carries every Euronext venue. Each national universe module only keeps
rows whose ``market`` column mentions its venue (for example ``Euronext
Oslo`` or ``Euronext Lisbon``), so one venue is never filtered out of
another venue's table.
"""

from __future__ import annotations

import csv
import io
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Mapping, Optional
from urllib.request import Request

DEFAULT_USER_AGENT = "InvestmentMonitor/0.1 (internal workspace)"


def fetch_euronext_rows(
    url: str,
    opener: Callable[..., Any],
    venue: str,
) -> List[Mapping[str, Any]]:
    """Fetch the shared CSV and return rows whose market mentions venue."""
    request = Request(
        url,
        headers={
            "User-Agent": DEFAULT_USER_AGENT,
            "Accept": "text/csv",
            "Accept-Language": "en;q=0.9",
        },
        method="GET",
    )
    with opener(request, timeout=60) as response:
        raw = response.read()
    text = raw.decode("utf-8-sig", errors="replace")
    reader = csv.reader(io.StringIO(text), delimiter=";")
    rows: List[Mapping[str, Any]] = []
    seen_header = False
    for row in reader:
        if not row or not row[0]:
            continue
        if not seen_header:
            if str(row[0]).strip() == "Name" and len(row) >= 5:
                seen_header = True
            continue
        if len(row) < 5:
            continue
        market = str(row[3]).strip()
        if venue not in market:
            continue
        symbol = str(row[2]).strip()
        if not symbol or symbol == "-":
            continue
        rows.append({
            "name": str(row[0]).strip(),
            "isin": str(row[1]).strip(),
            "symbol": symbol,
            "market": market,
        })
    return rows


def write_universe_cache(
    cache_path: Path,
    payload: Mapping[str, Any],
) -> None:
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = cache_path.with_suffix(cache_path.suffix + ".tmp")
    with temporary_path.open("w", encoding="utf-8") as cache_file:
        json.dump(payload, cache_file, ensure_ascii=False)
    temporary_path.replace(cache_path)


def build_universe_payload(
    rows: List[Mapping[str, Any]],
    normalize: Callable[[str], str],
    source: str,
    refreshed_at: Optional[str] = None,
) -> Mapping[str, Any]:
    entries: Dict[str, Mapping[str, Any]] = {}
    counts: Dict[str, int] = {}
    for row in rows:
        ticker = normalize(str(row["symbol"]))
        if not ticker or ticker in entries:
            continue
        board = str(row["market"])
        entries[ticker] = {
            "ticker": ticker,
            "name": str(row["name"] or ticker),
            "isin": str(row["isin"] or ""),
            "board": board,
            "exchange": board,
            "status": "active",
        }
        counts[board] = counts.get(board, 0) + 1
    return {
        "updated_at": refreshed_at or datetime.now(timezone.utc).isoformat(),
        "source": [source],
        "counts": counts,
        "items": sorted(entries.values(), key=lambda item: item["ticker"]),
    }
