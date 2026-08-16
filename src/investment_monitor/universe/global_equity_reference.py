# -*- coding: utf-8 -*-
"""Global equity reference: third-party candidate directory for stock/ETF.

Phase 1 contract (plan §4.2/§4.3/§6.2). The cache is a candidate layer
with ``source_tier="third_party"``: it may fill ETF gaps and add ISIN/FIGI
enrichment but must never silently overwrite official universe fields
(DE/IN/Euronext official caches always win for the same symbol/ISIN).

Cache path: ``.cache/investment_monitor/global_equity_reference.json``
(the daily EODHD budget lives inside the same payload so the rotation
survives restarts).
"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Mapping, Optional, Tuple

LOGGER = logging.getLogger(__name__)

DEFAULT_CACHE_PATH = ".cache/investment_monitor/global_equity_reference.json"
DEFAULT_DAILY_BUDGET = 20  # EODHD free tier: ~20 successful calls/day.

INSTRUMENT_TYPES = frozenset({"stock", "etf"})
SOURCE_TIERS = frozenset({"third_party"})


class GlobalEquityReferenceError(RuntimeError):
    """Raised when the reference pipeline is fatally misconfigured."""


def _cache_path(path: Optional[Path]) -> Path:
    return Path(
        path
        or os.environ.get(
            "GLOBAL_EQUITY_REFERENCE_CACHE_PATH", DEFAULT_CACHE_PATH
        )
    )


def _today_iso() -> str:
    return datetime.now(timezone.utc).date().isoformat()


def _daily_budget_limit() -> int:
    """Parse ``EODHD_DAILY_BUDGET`` tolerantly; invalid values fall back."""
    raw = os.environ.get("EODHD_DAILY_BUDGET", str(DEFAULT_DAILY_BUDGET))
    try:
        parsed = int(str(raw).strip())
    except (TypeError, ValueError):
        return DEFAULT_DAILY_BUDGET
    return parsed if parsed > 0 else DEFAULT_DAILY_BUDGET


def empty_payload() -> Dict[str, Any]:
    return {
        "updated_at": None,
        "source": ["global_equity_reference"],
        "source_tier": "third_party",
        "daily_budget": {
            "limit": _daily_budget_limit(),
            "date": _today_iso(),
            "used_calls": 0,
            "refreshed_exchanges": [],
        },
        "markets": {},
        "items": [],
    }


def load_global_equity_reference(
    path: Optional[Path] = None,
) -> Optional[Mapping[str, Any]]:
    cache_file = _cache_path(path)
    if not cache_file.exists():
        return None
    try:
        with cache_file.open(encoding="utf-8") as handle:
            return json.load(handle)
    except (OSError, json.JSONDecodeError):
        return None


def save_global_equity_reference(
    payload: Mapping[str, Any],
    path: Optional[Path] = None,
) -> None:
    cache_file = _cache_path(path)
    cache_file.parent.mkdir(parents=True, exist_ok=True)
    temporary = cache_file.with_suffix(cache_file.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=1)
    temporary.replace(cache_file)


def refresh_global_equity_reference(
    *,
    eodhd_client: Optional[Callable[..., Any]] = None,
    figi_client: Optional[Callable[..., Any]] = None,
    twelve_client: Optional[Callable[..., Any]] = None,
    official_name_maps: Optional[Mapping[str, Mapping[str, Mapping[str, str]]]] = None,
    exchanges: Optional[Mapping[str, str]] = None,
    path: Optional[Path] = None,
) -> Mapping[str, Any]:
    """Run the third-party candidate pipeline and return the cache payload.

    Missing keys never raise fatally: the corresponding stage reports
    ``skipped_*_no_key`` in the payload status. Official universe entries
    win for the same symbol/ISIN (merge rule in :func:`_merge_candidates`).
    """
    status: Dict[str, Any] = {"stages": {}, "errors": []}
    candidates: List[Dict[str, Any]] = []
    budget = _load_or_new_budget(path)

    if eodhd_client is None:
        from .eodhd_client import collect_eodhd_symbols

        eodhd_client = collect_eodhd_symbols
    if figi_client is None:
        from .openfigi_client import enrich_with_openfigi

        figi_client = enrich_with_openfigi
    if twelve_client is None:
        from .twelve_data_client import enrich_with_twelve_quotes

        twelve_client = enrich_with_twelve_quotes

    if os.environ.get("EODHD_API_KEY"):
        try:
            fetched, used = eodhd_client(
                exchanges=exchanges or _default_exchange_map(),
                budget=budget,
            )
            candidates.extend(fetched)
            budget["used_calls"] += used
        except Exception as error:  # noqa: BLE001 - 管线统一收编
            LOGGER.warning("global_equity_reference eodhd failed: %s", error)
            status["stages"]["eodhd"] = f"failed:{error}"
            status["errors"].append(str(error))
        else:
            status["stages"]["eodhd"] = f"ok:{budget['used_calls']}calls"
    else:
        status["stages"]["eodhd"] = "skipped_eodhd_no_key"

    if candidates:
        try:
            candidates = figi_client(candidates)
        except Exception as error:  # noqa: BLE001
            LOGGER.warning("global_equity_reference openfigi failed: %s", error)
            status["stages"]["openfigi"] = f"failed:{error}"
            status["errors"].append(str(error))
        else:
            status["stages"]["openfigi"] = f"ok:{len(candidates)}rows"
    else:
        status["stages"]["openfigi"] = "skipped_empty"

    if os.environ.get("TWELVE_DATA_API_KEY") and candidates:
        try:
            candidates = twelve_client(candidates)
        except Exception as error:  # noqa: BLE001
            status["stages"]["twelve"] = f"failed:{error}"
            status["errors"].append(str(error))
        else:
            status["stages"]["twelve"] = f"ok:{len(candidates)}rows"
    else:
        status["stages"]["twelve"] = "skipped_twelve_no_key"

    merged = _merge_candidates(
        candidates,
        official_name_maps
        if official_name_maps is not None
        else build_official_name_maps(),
    )
    payload = {
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "source": ["eodhd", "openfigi", "twelve_data"],
        "source_tier": "third_party",
        "status": status,
        "daily_budget": budget,
        "markets": _group_by_market(merged),
        "items": merged,
    }
    save_global_equity_reference(payload, path)
    return payload


def _load_or_new_budget(path: Optional[Path]) -> Dict[str, Any]:
    payload = load_global_equity_reference(path)
    budget = (payload or {}).get("daily_budget")
    if not isinstance(budget, dict) or budget.get("date") != _today_iso():
        return {
            "limit": _daily_budget_limit(),
            "date": _today_iso(),
            "used_calls": 0,
            "refreshed_exchanges": [],
        }
    budget.setdefault("refreshed_exchanges", [])
    return budget


def _isin_index(
    market_map: Mapping[str, Mapping[str, str]],
) -> Mapping[str, Mapping[str, str]]:
    """Build ISIN -> official entry once per market (first entry wins)."""
    index: Dict[str, Mapping[str, str]] = {}
    for official in market_map.values():
        isin = str(official.get("isin") or "").strip().upper()
        if isin and isin not in index:
            index[isin] = official
    return index


def _merge_candidates(
    candidates: List[Mapping[str, Any]],
    official_name_maps: Mapping[str, Mapping[str, Mapping[str, str]]],
) -> List[Dict[str, Any]]:
    merged: Dict[Tuple[str, str, str], Dict[str, Any]] = {}
    isin_indexes: Dict[str, Mapping[str, Mapping[str, str]]] = {}
    for candidate in candidates:
        market = str(candidate.get("market") or "")
        symbol = str(candidate.get("symbol") or "").upper()
        isin = str(candidate.get("isin") or "").upper()
        key = (market, symbol, isin)
        entry = dict(candidate)
        entry["source_tier"] = "third_party"
        entry.setdefault("instrument_type", "stock")
        entry.setdefault("verified_at", None)
        entry.setdefault("fund_family", "")
        entry.setdefault("domicile", "")
        entry.setdefault("benchmark", "")
        entry.setdefault("distributing_or_accumulating", "")
        market_map = official_name_maps.get(market, {})
        official = market_map.get(symbol)
        if official is None and isin:
            # 同 ISIN 也锚到官方条目（候选符号别名不同时仍然官方优先）。
            if market not in isin_indexes:
                isin_indexes[market] = _isin_index(market_map)
            official = isin_indexes[market].get(isin)
        if official:
            # 官方字段优先：同名/同 ISIN 的官方条目覆盖候选展示字段，
            # 候选只保留 provenance 与官方缺失的补充字段。
            entry["name"] = str(
                official.get("name")
                or candidate.get("name")
                or symbol
            )
            entry["isin"] = official.get("isin") or candidate.get("isin") or ""
            entry["board"] = official.get("board") or candidate.get("board") or ""
        else:
            entry["name"] = str(candidate.get("name") or symbol)
        merged[key] = entry
    return sorted(merged.values(), key=lambda item: (item["market"], item["symbol"]))


def _group_by_market(items: List[Mapping[str, Any]]) -> Dict[str, List[Dict[str, Any]]]:
    grouped: Dict[str, List[Dict[str, Any]]] = {}
    for item in items:
        grouped.setdefault(str(item["market"]), []).append(dict(item))
    return grouped


def search_global_equity_reference(
    query: str,
    *,
    market: Optional[str] = None,
    instrument_type: Optional[str] = None,
    path: Optional[Path] = None,
) -> List[Mapping[str, Any]]:
    payload = load_global_equity_reference(path)
    if not payload:
        return []
    needle = str(query or "").strip().lower()
    matches: List[Mapping[str, Any]] = []
    for item in payload.get("items") or []:
        if market and item.get("market") != market:
            continue
        if instrument_type and item.get("instrument_type") != instrument_type:
            continue
        if needle:
            haystack = (
                f"{item.get('symbol') or ''} "
                f"{item.get('isin') or ''} "
                f"{item.get('name') or ''} "
                f"{item.get('figi') or ''}"
            ).lower()
            if needle not in haystack:
                continue
        matches.append(dict(item))
        if len(matches) >= 100:
            break
    return matches


def etf_candidates_for(
    market: str,
    path: Optional[Path] = None,
) -> List[Mapping[str, Any]]:
    return search_global_equity_reference(
        "", market=market, instrument_type="etf", path=path
    )


def euronext_etf_candidates(
    markets: Optional[List[str]] = None,
    path: Optional[Path] = None,
) -> List[Mapping[str, Any]]:
    """ETF candidates for the Euronext ETF pillar (BE/FR/NL/IT, NO/PT optional)."""
    wanted = markets or ["be", "fr", "nl", "it"]
    payload = load_global_equity_reference(path)
    if not payload:
        return []
    result: List[Mapping[str, Any]] = []
    for item in payload.get("items") or []:
        if item.get("market") in wanted and item.get("instrument_type") == "etf":
            result.append(dict(item))
    return result


def build_official_name_maps(
    paths: Optional[Mapping[str, Path]] = None,
) -> Mapping[str, Mapping[str, Mapping[str, str]]]:
    """Collect official universe name maps (DE + Euronext markets).

    These are the Phase 1 "official wins" anchors: for the same symbol the
    official cache fields overwrite third-party candidates during merge.
    """
    from .be_universe import be_universe_name_map
    from .de_universe import de_universe_name_map
    from .fr_universe import fr_universe_name_map
    from .it_universe import it_universe_name_map
    from .nl_universe import nl_universe_name_map

    paths = paths or {}
    return {
        "de": de_universe_name_map(paths.get("de")),
        "be": be_universe_name_map(paths.get("be")),
        "fr": fr_universe_name_map(paths.get("fr")),
        "nl": nl_universe_name_map(paths.get("nl")),
        "it": it_universe_name_map(paths.get("it")),
    }


def _default_exchange_map() -> Mapping[str, str]:
    """market -> EODHD exchange code for venues we can map confidently.

    Unmapped markets are deliberately absent (callers skip them) instead
    of being guessed.
    """
    return {
        "us": "US",
        "de": "XETRA",
        "be": "BRU",
        "fr": "PAR",
        "nl": "AMS",
        "it": "MIL",
        "no": "OSL",
        "pt": "LIS",
        "at": "VI",
        "pl": "WSE",
        "ch": "SW",
        "es": "MCE",
        "se": "ST",
        "dk": "CO",
        "fi": "HE",
        "ie": "IR",
        "gb": "LSE",
        "uk": "LSE",
    }


__all__ = [
    "GlobalEquityReferenceError",
    "build_official_name_maps",
    "empty_payload",
    "etf_candidates_for",
    "euronext_etf_candidates",
    "load_global_equity_reference",
    "refresh_global_equity_reference",
    "save_global_equity_reference",
    "search_global_equity_reference",
]
