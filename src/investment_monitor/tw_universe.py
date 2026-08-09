"""TW tradeable universe cache (breadth only) from TWSE/TPEx directories.

Sources (live verified 2026-08-07): TWSE listed basic information
(``t187ap03_L``, 1093 rows, traditional-Chinese keys) and TPEx OTC basic
information (``mopsfin_t187ap03_O``, 890 rows, English keys). The TPEx
emerging (興櫃) ``*_U`` endpoint redirects to the TPEx homepage HTML, so
emerging coverage is an opt-in env hook (``TW_UNIVERSE_EMERGING_URL``)
parsing the same TPEx shape; it is not wired by default. The cache is
breadth only and never flows into information_items / Today feed.
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

from .sources.twse_material.client import normalize_tw_ticker

LOGGER = logging.getLogger(__name__)

DEFAULT_CACHE_PATH = ".cache/investment_monitor/tw_universe.json"
TWSE_LISTED_URL = "https://openapi.twse.com.tw/v1/opendata/t187ap03_L"
TPEX_OTC_URL = "https://www.tpex.org.tw/openapi/v1/mopsfin_t187ap03_O"
EMERGING_URL_ENV = "TW_UNIVERSE_EMERGING_URL"
DEFAULT_USER_AGENT = "InvestmentMonitor/0.1 (internal workspace)"


class TwUniverseError(RuntimeError):
    """Raised when the TW universe cannot be refreshed at all."""


def load_tw_universe(
    path: Optional[Path] = None,
) -> Optional[Mapping[str, Any]]:
    """Load the cached universe payload, or None when absent/invalid."""
    cache_path = _cache_path(path)
    try:
        with cache_path.open("r", encoding="utf-8") as cache_file:
            return json.load(cache_file)
    except (OSError, json.JSONDecodeError):
        return None


def refresh_tw_universe(
    *,
    path: Optional[Path] = None,
    twse_opener: Optional[Callable[..., Any]] = None,
    tpex_opener: Optional[Callable[..., Any]] = None,
    emerging_opener: Optional[Callable[..., Any]] = None,
    emerging_url: Optional[str] = None,
    refreshed_at: Optional[str] = None,
) -> Mapping[str, Any]:
    """Refresh the TW universe from TWSE/TPEx open company directories.

    Each board is fetched independently; a failed board is logged and the
    successful boards are still merged (a full failure raises
    ``TwUniverseError``). Emerging (興櫃) is fetched only when an explicit
    ``emerging_url`` / ``TW_UNIVERSE_EMERGING_URL`` is configured.
    """
    cache_path = _cache_path(path)
    verify_ssl = (
        os.environ.get("TW_UNIVERSE_VERIFY_SSL", "true")
        .strip()
        .lower()
    ) not in {"0", "false", "no", "off"}
    default_opener = _make_opener(verify_ssl)
    emerging_url = emerging_url or os.environ.get(EMERGING_URL_ENV)

    entries: Dict[str, Mapping[str, Any]] = {}
    counts = {"TWSE": 0, "TPEx": 0, "ESB": 0}
    sources: List[str] = []

    jobs = [
        (
            "TWSE",
            "twse_openapi",
            twse_opener or default_opener,
            TWSE_LISTED_URL,
            _parse_twse_rows,
        ),
        (
            "TPEx",
            "tpex_openapi",
            tpex_opener or default_opener,
            TPEX_OTC_URL,
            _parse_tpex_rows,
        ),
    ]
    if emerging_url:
        jobs.append(
            (
                "ESB",
                "tpex_emerging_openapi",
                emerging_opener or default_opener,
                emerging_url,
                _parse_tpex_rows,
            )
        )

    for board, source_name, opener, url, parser in jobs:
        try:
            rows = parser(_get_json(url, opener))
        except Exception as error:
            LOGGER.warning(
                "tw_universe board=%s source=%s failed: %s",
                board,
                source_name,
                error,
            )
            continue
        for row in rows:
            ticker = str(row.get("ticker") or "")
            if not ticker or ticker in entries:
                continue
            entries[ticker] = {
                "ticker": ticker,
                "name": str(row.get("name") or ""),
                "name_zh": str(row.get("name_zh") or ""),
                "name_en": str(row.get("name_en") or ""),
                "industry": str(row.get("industry") or ""),
                "board": board,
                "exchange": board,
                "status": "active",
            }
            counts[board] += 1
        if rows:
            sources.append(source_name)

    if not entries:
        raise TwUniverseError(
            "All TW universe sources failed; no entries available."
        )

    payload = {
        "updated_at": (
            refreshed_at
            or datetime.now(timezone.utc).isoformat()
        ),
        "source": sorted(sources),
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


def tw_universe_name_map(
    path: Optional[Path] = None,
) -> Mapping[str, Mapping[str, str]]:
    """Return ticker -> {name, exchange} for web add-company fallback."""
    payload = load_tw_universe(path)
    if not payload:
        return {}
    result: Dict[str, Mapping[str, str]] = {}
    for item in payload.get("items") or []:
        ticker = str(item.get("ticker") or "").strip()
        if not ticker:
            continue
        result[ticker] = {
            "name": str(
                item.get("name_zh")
                or item.get("name")
                or ticker
            ),
            "exchange": str(item.get("board") or "TWSE"),
        }
    return result


def search_tw_universe(
    query: str,
    path: Optional[Path] = None,
) -> List[Mapping[str, Any]]:
    """Search the cached TW universe by ticker or name substring."""
    payload = load_tw_universe(path)
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
            f"{item.get('name_zh') or ''} "
            f"{item.get('name_en') or ''}"
        ).lower()
        if needle in haystack:
            matches.append(dict(item))
        if len(matches) >= 50:
            break
    return matches


def _parse_twse_rows(rows: Any) -> List[Mapping[str, Any]]:
    if not isinstance(rows, list):
        raise TwUniverseError("TWSE listed response was not a JSON array.")
    records = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        code = normalize_tw_ticker(str(row.get("公司代號") or ""))
        name = str(row.get("公司名稱") or "").strip()
        short = str(row.get("公司簡稱") or "").strip()
        if not code or not name:
            continue
        records.append(
            {
                "ticker": code,
                "name": name,
                "name_zh": name,
                "name_en": str(row.get("英文簡稱") or "").strip(),
                "industry": str(row.get("產業別") or "").strip(),
            }
        )
    return records


def _parse_tpex_rows(rows: Any) -> List[Mapping[str, Any]]:
    if not isinstance(rows, list):
        raise TwUniverseError("TPEx response was not a JSON array.")
    records = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        code = normalize_tw_ticker(
            str(row.get("SecuritiesCompanyCode") or "")
        )
        name = str(row.get("CompanyName") or "").strip()
        if not code or not name:
            continue
        records.append(
            {
                "ticker": code,
                "name": name,
                "name_zh": name,
                "name_en": str(row.get("Symbol") or "").strip(),
                "industry": str(
                    row.get("SecuritiesIndustryCode") or ""
                ).strip(),
            }
        )
    return records


def _get_json(
    url: str,
    opener: Callable[..., Any],
) -> Any:
    request = Request(
        url,
        headers={
            "User-Agent": DEFAULT_USER_AGENT,
            "Accept": "application/json",
            "Accept-Language": "zh-TW,en;q=0.8",
        },
        method="GET",
    )
    with opener(request, timeout=30) as response:
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
        path or os.environ.get("TW_UNIVERSE_CACHE_PATH", DEFAULT_CACHE_PATH)
    )
