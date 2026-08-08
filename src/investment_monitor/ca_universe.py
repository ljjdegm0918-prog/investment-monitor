"""CA tradeable universe cache (breadth only) from TSX/TSXV directories.

Sources (live verified 2026-08-08): TSX company directory JSON
(``https://www.tsx.com/json/company-directory/search/tsx/^``, ~2264
results / ~2997 instruments) and TSX Venture company directory JSON
(``https://www.tsx.com/json/company-directory/search/tsxv/^``, ~1433
results / ~1479 instruments); both are key-free official TMX JSON. CSE
(``api.thecse.com``) fails the TLS handshake from the current network on
both OpenSSL and Schannel, and NEO returns Cloudflare 522 origin timeouts,
so those boards are not wired yet. The cache is breadth only and never
flows into information_items / Today feed.
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

from .web_repository import normalize_ca_ticker

LOGGER = logging.getLogger(__name__)

DEFAULT_CACHE_PATH = ".cache/investment_monitor/ca_universe.json"
TSX_URL = "https://www.tsx.com/json/company-directory/search/tsx/^"
TSXV_URL = "https://www.tsx.com/json/company-directory/search/tsxv/^"
TSX_URL_ENV = "CA_TSX_UNIVERSE_URL"
TSXV_URL_ENV = "CA_TSXV_UNIVERSE_URL"
DEFAULT_USER_AGENT = "InvestmentMonitor/0.1 (internal workspace)"


class CaUniverseError(RuntimeError):
    """Raised when the CA universe cannot be refreshed at all."""


def load_ca_universe(
    path: Optional[Path] = None,
) -> Optional[Mapping[str, Any]]:
    """Load the cached universe payload, or None when absent/invalid."""
    cache_path = _cache_path(path)
    try:
        with cache_path.open("r", encoding="utf-8") as cache_file:
            return json.load(cache_file)
    except (OSError, json.JSONDecodeError):
        return None


def refresh_ca_universe(
    *,
    path: Optional[Path] = None,
    tsx_opener: Optional[Callable[..., Any]] = None,
    tsxv_opener: Optional[Callable[..., Any]] = None,
    tsx_url: Optional[str] = None,
    tsxv_url: Optional[str] = None,
    refreshed_at: Optional[str] = None,
) -> Mapping[str, Any]:
    """Refresh the CA universe from the TSX/TSXV company directories.

    Each board is fetched independently; a failed board is logged and the
    successful boards are still merged (a full failure raises
    ``CaUniverseError``). Board URLs can be overridden through
    ``CA_TSX_UNIVERSE_URL`` / ``CA_TSXV_UNIVERSE_URL``.
    """
    cache_path = _cache_path(path)
    verify_ssl = (
        os.environ.get("CA_UNIVERSE_VERIFY_SSL", "true")
        .strip()
        .lower()
    ) not in {"0", "false", "no", "off"}
    default_opener = _make_opener(verify_ssl)

    entries: Dict[str, Mapping[str, Any]] = {}
    counts = {"TSX": 0, "TSXV": 0}
    sources: List[str] = []

    jobs = [
        (
            "TSX",
            "tsx_directory",
            tsx_opener or default_opener,
            tsx_url or os.environ.get(TSX_URL_ENV, TSX_URL),
            _parse_directory_rows,
        ),
        (
            "TSXV",
            "tsxv_directory",
            tsxv_opener or default_opener,
            tsxv_url or os.environ.get(TSXV_URL_ENV, TSXV_URL),
            _parse_directory_rows,
        ),
    ]

    for board, source_name, opener, url, parser in jobs:
        try:
            rows = parser(_get_json(url, opener), board)
        except Exception as error:
            LOGGER.warning(
                "ca_universe board=%s source=%s failed: %s",
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
                "name": str(row.get("name") or ticker),
                "board": board,
                "exchange": board,
                "status": "active",
            }
            counts[board] += 1
        if rows:
            sources.append(source_name)

    if not entries:
        raise CaUniverseError(
            "All CA universe sources failed; no entries available."
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


def ca_universe_name_map(
    path: Optional[Path] = None,
) -> Mapping[str, Mapping[str, str]]:
    """Return normalized ticker -> {name, exchange} for web fallback."""
    payload = load_ca_universe(path)
    if not payload:
        return {}
    result: Dict[str, Mapping[str, str]] = {}
    for item in payload.get("items") or []:
        ticker = str(item.get("ticker") or "").strip()
        if not ticker:
            continue
        result[ticker] = {
            "name": str(item.get("name") or ticker),
            "exchange": str(item.get("board") or "TSX"),
        }
    return result


def search_ca_universe(
    query: str,
    path: Optional[Path] = None,
) -> List[Mapping[str, Any]]:
    """Search the cached CA universe by ticker or name substring."""
    payload = load_ca_universe(path)
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


def _parse_directory_rows(
    data: Any,
    board: str,
) -> List[Mapping[str, Any]]:
    if not isinstance(data, dict):
        raise CaUniverseError(
            f"{board} directory response was not a JSON object."
        )
    if data.get("isHttpError"):
        raise CaUniverseError(
            f"{board} directory response reported isHttpError."
        )
    results = data.get("results")
    if not isinstance(results, list):
        raise CaUniverseError(
            f"{board} directory response had no results list."
        )
    records: List[Mapping[str, Any]] = []
    for result in results:
        if not isinstance(result, dict):
            continue
        result_symbol = str(result.get("symbol") or "")
        result_name = str(result.get("name") or "").strip()
        instruments = result.get("instruments")
        if isinstance(instruments, list) and instruments:
            for instrument in instruments:
                if not isinstance(instrument, dict):
                    continue
                symbol = str(instrument.get("symbol") or result_symbol)
                name = str(
                    instrument.get("name") or result_name or symbol
                ).strip()
                ticker = normalize_ca_ticker(symbol)
                if ticker and name:
                    records.append({"ticker": ticker, "name": name})
        else:
            ticker = normalize_ca_ticker(result_symbol)
            if ticker and result_name:
                records.append(
                    {"ticker": ticker, "name": result_name}
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
        path or os.environ.get("CA_UNIVERSE_CACHE_PATH", DEFAULT_CACHE_PATH)
    )
