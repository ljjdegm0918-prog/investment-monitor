# -*- coding: utf-8 -*-
"""Official Austrian equity universe from the Wiener Börse company list.

The public page is server rendered and carries ISIN, issuer, country, market,
segment, and security type for every row.  It does not publish a ticker in the
table, so the official ISIN is the canonical key unless an audited local
overlay supplies a ticker.  Foreign ``global market`` convenience listings
and fund/certificate rows are excluded from the Austrian issuer universe.
"""

from __future__ import annotations

import html
import json
import logging
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Mapping, Optional, Sequence
from urllib.parse import parse_qs, urljoin, urlparse

from ..web_repository import normalize_at_ticker
from ..sources._public_disclosure import clean_html, fetch_text

LOGGER = logging.getLogger(__name__)

DEFAULT_CACHE_PATH = ".cache/investment_monitor/at_universe.json"
DIRECTORY_URL = "https://www.wienerborse.at/en/listing/shares/companies-list/"
OVERLAY_ENV = "AT_UNIVERSE_OVERLAY_PATH"
OVERLAY_SCHEMA = "at_universe_overlay/v1"
MIN_AUSTRIAN_EQUITIES = 40
_EQUITY_TYPES = frozenset(
    {"Equity Share", "Registered Ordinary Share", "Preferred Share", "Depository Interest"}
)


class AtUniverseError(RuntimeError):
    """Raised when the official AT universe cannot be validated."""


def _cache_path(path: Optional[Path]) -> Path:
    return Path(path or os.environ.get("AT_UNIVERSE_CACHE_PATH", DEFAULT_CACHE_PATH))


def load_at_universe(path: Optional[Path] = None) -> Optional[Mapping[str, Any]]:
    cache_file = _cache_path(path)
    if not cache_file.exists():
        return None
    try:
        with cache_file.open(encoding="utf-8") as handle:
            payload = json.load(handle)
    except (OSError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, Mapping) else None


def parse_at_company_page(
    text: str,
    *,
    minimum_items: int = MIN_AUSTRIAN_EQUITIES,
) -> Sequence[Mapping[str, Any]]:
    """Parse and validate the official Wiener Börse listed-company table."""
    visible = clean_html(text).casefold()
    if any(marker in visible for marker in ("access denied", "loading...", "sign in")):
        raise AtUniverseError("Wiener Börse returned an access/loading page")
    table_match = re.search(
        r'<table\b[^>]*class=["\'][^"\']*kv-grid-table[^"\']*["\'][^>]*>'
        r'(.*?)</table>',
        text,
        flags=re.I | re.S,
    )
    if not table_match:
        raise AtUniverseError("Wiener Börse company table is missing")
    table = table_match.group(1)
    header_match = re.search(r"<thead>(.*?)</thead>", table, flags=re.I | re.S)
    if not header_match:
        raise AtUniverseError("Wiener Börse company table header is missing")
    headers = tuple(
        clean_html(value)
        for value in re.findall(r"<th\b[^>]*>(.*?)</th>", header_match.group(1), re.I | re.S)
    )
    expected = ("ISIN", "Issuer", "Country", "Market", "Market Segment", "Type of Security")
    if headers != expected:
        raise AtUniverseError(f"Wiener Börse company columns changed: {headers!r}")

    entries: List[Mapping[str, Any]] = []
    seen_isins: set[str] = set()
    candidate_rows = re.findall(
        r'<tr\b[^>]*data-key=["\'][^"\']+["\'][^>]*>(.*?)</tr>',
        table,
        flags=re.I | re.S,
    )
    if not candidate_rows:
        raise AtUniverseError("Wiener Börse company table has no data rows")
    for row in candidate_rows:
        cells = re.findall(r"<td\b[^>]*>(.*?)</td>", row, flags=re.I | re.S)
        if len(cells) != 6:
            raise AtUniverseError("Wiener Börse company row column count changed")
        isin, issuer, country, market, segment, security_type = tuple(clean_html(cell) for cell in cells)
        link_match = re.search(r'<a\b[^>]*href=["\']([^"\']+)["\']', cells[1], flags=re.I)
        if not link_match:
            raise AtUniverseError("Wiener Börse company row is missing its profile link")
        profile_url = urljoin(DIRECTORY_URL, html.unescape(link_match.group(1)))
        profile_isin = str((parse_qs(urlparse(profile_url).query).get("ISIN") or [""])[0]).upper()
        if not re.fullmatch(r"[A-Z]{2}[A-Z0-9]{10}", isin):
            raise AtUniverseError(f"Wiener Börse company row has invalid ISIN: {isin!r}")
        if profile_isin != isin:
            raise AtUniverseError(f"Wiener Börse profile ISIN mismatch for {isin}")
        if not issuer or not country or not segment or not security_type:
            raise AtUniverseError("Wiener Börse company row is missing identity fields")
        if country != "Austria" or segment.casefold() == "global market":
            continue
        if security_type not in _EQUITY_TYPES:
            continue
        if isin in seen_isins:
            raise AtUniverseError(f"Wiener Börse company table repeated ISIN {isin}")
        seen_isins.add(isin)
        entries.append(
            {
                "ticker": isin,
                "isin": isin,
                "name": issuer,
                "country": country,
                "exchange": "Wiener Börse",
                "market": market if market != "-" else "Vienna MTF",
                "board": segment,
                "security_type": security_type,
                "profile_url": profile_url,
                "source": "wiener_boerse_official_company_list",
                "aliases": [],
            }
        )
    if len(entries) < minimum_items:
        raise AtUniverseError(
            f"Wiener Börse company table is suspiciously small: {len(entries)} < {minimum_items}"
        )
    return tuple(entries)


def _load_overlay(path: Optional[Path]) -> Mapping[str, Mapping[str, Any]]:
    overlay_path = path or (Path(os.environ[OVERLAY_ENV]) if os.environ.get(OVERLAY_ENV) else None)
    if overlay_path is None:
        return {}
    try:
        payload = json.loads(Path(overlay_path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise AtUniverseError(f"AT universe overlay could not be read: {error}") from error
    if not isinstance(payload, Mapping) or payload.get("schema") != OVERLAY_SCHEMA:
        raise AtUniverseError(f"AT universe overlay must use schema {OVERLAY_SCHEMA}")
    mappings = payload.get("mappings")
    if not isinstance(mappings, list):
        raise AtUniverseError("AT universe overlay mappings must be a list")
    result: Dict[str, Mapping[str, Any]] = {}
    seen_keys: set[str] = set()
    for mapping in mappings:
        if not isinstance(mapping, Mapping):
            raise AtUniverseError("AT universe overlay mapping must be an object")
        isin = str(mapping.get("isin") or "").strip().upper()
        ticker = normalize_at_ticker(str(mapping.get("ticker") or ""))
        aliases = mapping.get("aliases") or []
        if not re.fullmatch(r"[A-Z]{2}[A-Z0-9]{10}", isin) or not ticker:
            raise AtUniverseError("AT universe overlay requires valid isin and ticker")
        if not isinstance(aliases, list) or any(not str(alias).strip() for alias in aliases):
            raise AtUniverseError("AT universe overlay aliases must be non-empty strings")
        normalized_aliases = [normalize_at_ticker(str(alias)) for alias in aliases]
        local_keys = [ticker, *normalized_aliases]
        if (
            isin in result
            or any(not key for key in local_keys)
            or len(set(local_keys)) != len(local_keys)
            or any(key in seen_keys for key in local_keys)
        ):
            raise AtUniverseError("AT universe overlay contains duplicate ticker or alias")
        seen_keys.update(local_keys)
        result[isin] = {"ticker": ticker, "aliases": normalized_aliases}
    return result


def refresh_at_universe(
    *,
    path: Optional[Path] = None,
    overlay_path: Optional[Path] = None,
    fetcher: Callable[[str], Any] = fetch_text,
    url: str = DIRECTORY_URL,
    refreshed_at: Optional[str] = None,
    minimum_items: int = MIN_AUSTRIAN_EQUITIES,
) -> Mapping[str, Any]:
    """Refresh the official list atomically, applying only reviewed aliases."""
    try:
        response = fetcher(url)
        text = response[0] if isinstance(response, tuple) else response
        if not isinstance(text, str):
            raise AtUniverseError("Wiener Börse fetcher returned non-text data")
        official = parse_at_company_page(text, minimum_items=minimum_items)
        overlay = _load_overlay(overlay_path)
    except Exception as error:
        if isinstance(error, AtUniverseError):
            raise
        raise AtUniverseError(f"Wiener Börse company list failed: {error}") from error

    official_isins = {str(entry["isin"]) for entry in official}
    unknown_overlay = set(overlay) - official_isins
    if unknown_overlay:
        raise AtUniverseError(
            "AT universe overlay refers to unknown official ISIN(s): "
            + ", ".join(sorted(unknown_overlay))
        )
    items = []
    seen_keys: set[str] = set()
    for raw in official:
        entry = dict(raw)
        reviewed = overlay.get(str(entry["isin"]), {})
        entry["ticker"] = str(reviewed.get("ticker") or entry["isin"])
        entry["aliases"] = list(reviewed.get("aliases") or [])
        if entry["ticker"] in seen_keys:
            raise AtUniverseError(f"AT universe repeated canonical key {entry['ticker']}")
        seen_keys.add(str(entry["ticker"]))
        items.append(entry)
    payload = {
        "updated_at": refreshed_at or datetime.now(timezone.utc).isoformat(),
        "source": ["wiener_boerse_official_company_list"],
        "coverage": "official_austrian_equity_issuers",
        "counts": {
            "issuers": len(items),
            "regulated_market": sum(1 for item in items if item["market"] == "Regulated Market"),
            "vienna_mtf": sum(1 for item in items if item["market"] == "Vienna MTF"),
            "reviewed_tickers": len(overlay),
        },
        "items": sorted(items, key=lambda item: (str(item["name"]), str(item["isin"]))),
    }
    cache_file = _cache_path(path)
    cache_file.parent.mkdir(parents=True, exist_ok=True)
    temporary = cache_file.with_suffix(cache_file.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False)
    temporary.replace(cache_file)
    return payload


def at_universe_name_map(path: Optional[Path] = None) -> Mapping[str, Mapping[str, str]]:
    payload = load_at_universe(path)
    if not payload:
        return {}
    result: Dict[str, Mapping[str, str]] = {}
    for item in payload.get("items") or []:
        ticker = normalize_at_ticker(str(item.get("ticker") or item.get("isin") or ""))
        if not ticker:
            continue
        identity = {
            "name": str(item.get("name") or ticker),
            "exchange": str(item.get("exchange") or "Wiener Börse"),
            "board": str(item.get("board") or "Wiener Börse"),
            "isin": str(item.get("isin") or ""),
        }
        keys = [ticker, str(item.get("isin") or ""), *(item.get("aliases") or [])]
        for raw_key in keys:
            key = normalize_at_ticker(str(raw_key))
            if key and key not in result:
                result[key] = identity
    return result


def search_at_universe(query: str, path: Optional[Path] = None) -> List[Mapping[str, Any]]:
    payload = load_at_universe(path)
    if not payload:
        return []
    needle = str(query or "").strip().casefold()
    if not needle:
        return []
    matches: List[Mapping[str, Any]] = []
    for item in payload.get("items") or []:
        haystack = " ".join(
            str(value or "")
            for value in (
                item.get("ticker"), item.get("name"), item.get("isin"), item.get("board"),
                " ".join(str(alias) for alias in item.get("aliases") or []),
            )
        ).casefold()
        if needle in haystack:
            matches.append(dict(item))
        if len(matches) >= 50:
            break
    return matches


__all__ = [
    "AtUniverseError",
    "DIRECTORY_URL",
    "MIN_AUSTRIAN_EQUITIES",
    "OVERLAY_SCHEMA",
    "at_universe_name_map",
    "load_at_universe",
    "parse_at_company_page",
    "refresh_at_universe",
    "search_at_universe",
]
