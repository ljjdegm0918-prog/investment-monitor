"""HK tradeable universe cache (breadth only) from HKEXnews stock lists.

Source: HKEXnews active (and optionally inactive) stock lists. This is an
unofficial JSON mirror and may change without notice; it is NOT a complete
Hong Kong universe, and structured products / multi-counter edge cases
may be partial. The cache never flows into information_items / Today feed.
"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional

from .sources.hkexnews import HkexNewsClient, normalize_hk_ticker

LOGGER = logging.getLogger(__name__)

DEFAULT_CACHE_PATH = ".cache/investment_monitor/hk_universe.json"
SOURCE_NAME = "hkexnews_activestock"
EXCHANGE = "SEHK"


class HkUniverseError(RuntimeError):
    """Raised when the HK universe cannot be refreshed."""


def load_hk_universe(
    path: Optional[Path] = None,
) -> Optional[Mapping[str, Any]]:
    """Load the cached universe payload, or None when absent/invalid."""
    cache_path = _cache_path(path)
    try:
        with cache_path.open("r", encoding="utf-8") as cache_file:
            return json.load(cache_file)
    except (OSError, json.JSONDecodeError):
        return None


def refresh_hk_universe(
    *,
    path: Optional[Path] = None,
    include_inactive: bool = True,
    client: Optional[HkexNewsClient] = None,
    refreshed_at: Optional[str] = None,
) -> Mapping[str, Any]:
    """Refresh the HK universe cache from HKEXnews stock lists.

    ``include_inactive`` (default True) also records delisted/inactive codes
    with ``status="inactive"`` so they remain findable without pretending to
    have ongoing disclosure. ``name_map`` still prefers active entries.
    """
    cache_path = _cache_path(path)
    hkex_client = client or HkexNewsClient.from_environment()
    try:
        entries: Dict[str, Mapping[str, Any]] = _build_entries(
            hkex_client.fetch_stock_list("active", "e"),
            hkex_client.fetch_stock_list("active", "c"),
            status="active",
        )
        counts = {"active": len(entries), "inactive": 0}
        if include_inactive:
            inactive = _build_entries(
                hkex_client.fetch_stock_list("inactive", "e"),
                hkex_client.fetch_stock_list("inactive", "c"),
                status="inactive",
            )
            for code, entry in inactive.items():
                if code in entries:
                    if not entries[code].get("name_zh"):
                        entries[code] = {
                            **entries[code],
                            "name_zh": str(entry.get("name_zh") or ""),
                        }
                    continue
                entries[code] = entry
                counts["inactive"] += 1
    except Exception as error:
        raise HkUniverseError(f"hkexnews: {error}") from error

    payload = {
        "source": SOURCE_NAME,
        "refreshed_at": (
            refreshed_at
            or datetime.now(timezone.utc).isoformat()
        ),
        "counts": counts,
        "entries": entries,
    }
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = cache_path.with_suffix(cache_path.suffix + ".tmp")
    with temporary_path.open("w", encoding="utf-8") as cache_file:
        json.dump(payload, cache_file, ensure_ascii=False)
    temporary_path.replace(cache_path)
    return payload


def hk_universe_name_map(
    path: Optional[Path] = None,
) -> Mapping[str, Mapping[str, str]]:
    """Return normalized ticker -> {name, exchange, ...} for web fallback."""
    payload = load_hk_universe(path)
    if not payload:
        return {}
    result: Dict[str, Mapping[str, str]] = {}
    for ticker, entry in (payload.get("entries") or {}).items():
        code = normalize_hk_ticker(str(ticker))
        if not code:
            continue
        status = str(entry.get("status") or "active")
        if status == "inactive" and code in result:
            continue  # active entries win for add-company fallback
        result[code] = {
            "name": str(
                entry.get("name")
                or entry.get("name_zh")
                or code
            ),
            "exchange": str(entry.get("exchange") or EXCHANGE),
            "stock_id": str(entry.get("stock_id") or ""),
            "name_zh": str(entry.get("name_zh") or ""),
            "status": status,
        }
    return result


def _build_entries(
    rows_en: List[Mapping[str, Any]],
    rows_zh: List[Mapping[str, Any]],
    *,
    status: str,
) -> Dict[str, Mapping[str, Any]]:
    zh_by_code = {
        normalize_hk_ticker(str(row["stock_code"])): row
        for row in rows_zh
    }
    entries: Dict[str, Mapping[str, Any]] = {}
    for row in rows_en:
        code = normalize_hk_ticker(str(row["stock_code"]))
        zh = zh_by_code.get(code)
        entries[code] = {
            "ticker": code,
            "stock_id": str(row["stock_id"]),
            "name": str(row["stock_name"] or code),
            "name_zh": str(zh["stock_name"]) if zh else "",
            "exchange": EXCHANGE,
            "status": status,
        }
    # zh-only codes keep breadth without dropping data.
    for code, row in zh_by_code.items():
        if code in entries:
            continue
        entries[code] = {
            "ticker": code,
            "stock_id": str(row["stock_id"]),
            "name": str(row["stock_name"] or code),
            "name_zh": str(row["stock_name"] or ""),
            "exchange": EXCHANGE,
            "status": status,
        }
    return entries


def _cache_path(path: Optional[Path]) -> Path:
    return Path(
        path or os.environ.get("HK_UNIVERSE_CACHE_PATH", DEFAULT_CACHE_PATH)
    )
