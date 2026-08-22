"""Canada tradeable-universe cache from verified exchange sources.

TSX and TSXV are refreshed from their public directory JSON.  CSE is refreshed
from the same first-party JSON directory used by the public CSE listings page;
a human-reviewed official export remains available as an offline override.
Every network response is validated before it can replace the cache.

Items retain a listing per ``(exchange, symbol)``.  This preserves legitimate
cross-listings and lets a reviewed overlay describe a renamed issuer, while
``ca_universe_name_map`` remains the legacy one-entry-per-normalized-ticker
view used by the web fallback.
"""

from __future__ import annotations

import json
import logging
import os
import ssl
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Mapping, Optional
from urllib.parse import urlsplit
from urllib.request import HTTPSHandler, Request, build_opener, urlopen

from .web_repository import normalize_ca_ticker

LOGGER = logging.getLogger(__name__)

DEFAULT_CACHE_PATH = ".cache/investment_monitor/ca_universe.json"
TSX_URL = "https://www.tsx.com/json/company-directory/search/tsx/^"
TSXV_URL = "https://www.tsx.com/json/company-directory/search/tsxv/^"
CSE_URL = "https://website-data-api-v2.thecse.com/api/companies/all"
TSX_URL_ENV = "CA_TSX_UNIVERSE_URL"
TSXV_URL_ENV = "CA_TSXV_UNIVERSE_URL"
CSE_URL_ENV = "CA_CSE_UNIVERSE_URL"
DEFAULT_USER_AGENT = "InvestmentMonitor/0.1 (internal workspace)"
CSE_DIRECTORY_SOURCE = "cse_directory"
CSE_EXPORT_SOURCE = "cse_official_export"
CSE_OVERLAY_SOURCE = "ca_config_overlay"
CSE_EXPORT_PATH_ENV = "CA_CSE_UNIVERSE_EXPORT_PATH"
CA_OVERLAY_PATH_ENV = "CA_UNIVERSE_OVERLAY_PATH"
_CSE_HOSTS = {
    "thecse.com",
    "primary.thecse.com",
    "v3.thecse.com",
    "website-data-api-v2.thecse.com",
}
_EXCHANGE_PRIORITY = {"TSX": 0, "TSXV": 1, "CSE": 2}

# CSE 的公开官网目录和逐发行人 filing mirror 已于 2026-08-22 验证；
# NEO 仍未接入，SEDAR+ 公共站仍不能作为自动化批量来源。
PHASE4_BOUNDARY = {
    "universe": "partial",
    "disclosure": "partial",
    "evidence": (
        "CSE public first-party directory and issuer filing mirror connected; "
        "NEO not connected; SEDAR+ bulk automation not used; "
        "CEO.ca SEDAR PDF mirror remains third-party partial"
    ),
}


class CaUniverseError(RuntimeError):
    """Raised when the CA universe cannot be refreshed at all."""


def load_ca_universe(
    path: Optional[Path] = None,
) -> Optional[Mapping[str, Any]]:
    """Load the cached universe payload, or None when absent/invalid."""
    cache_path = _cache_path(path)
    try:
        with cache_path.open("r", encoding="utf-8") as cache_file:
            payload = json.load(cache_file)
    except (OSError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, Mapping) else None


def refresh_ca_universe(
    *,
    path: Optional[Path] = None,
    tsx_opener: Optional[Callable[..., Any]] = None,
    tsxv_opener: Optional[Callable[..., Any]] = None,
    cse_opener: Optional[Callable[..., Any]] = None,
    tsx_url: Optional[str] = None,
    tsxv_url: Optional[str] = None,
    cse_url: Optional[str] = None,
    refreshed_at: Optional[str] = None,
    cse_export: Optional[Mapping[str, Any]] = None,
    overlay: Optional[Mapping[str, Any]] = None,
) -> Mapping[str, Any]:
    """Refresh the CA universe from the TSX/TSXV company directories.

    Each board is fetched independently; a failed board is logged and the
    successful boards are still merged (a full failure raises
    ``CaUniverseError``). Board URLs can be overridden through
    ``CA_TSX_UNIVERSE_URL`` / ``CA_TSXV_UNIVERSE_URL``.  Unless an explicit
    ``cse_export`` is supplied, the first-party CSE company directory is also
    refreshed. ``cse_export`` is a previously downloaded official CSE export,
    not a URL. ``overlay`` is a local, reviewable configuration payload for
    corrections, profile links, or issuer renames. All inputs are strict.
    """
    cache_path = _cache_path(path)
    if cse_export is None:
        cse_export = _optional_json_mapping_from_env(CSE_EXPORT_PATH_ENV)
    if overlay is None:
        overlay = _optional_json_mapping_from_env(CA_OVERLAY_PATH_ENV)
    verify_ssl = (
        os.environ.get("CA_UNIVERSE_VERIFY_SSL", "true")
        .strip()
        .lower()
    ) not in {"0", "false", "no", "off"}
    default_opener = _make_opener(verify_ssl)

    verified_at = _validated_timestamp(
        refreshed_at or datetime.now(timezone.utc).isoformat(),
        field="refreshed_at",
    )
    entries: Dict[str, Mapping[str, Any]] = {}
    counts = {"TSX": 0, "TSXV": 0, "CSE": 0}
    sources: List[str] = []
    failures: Dict[str, str] = {}

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

    if cse_export is None:
        jobs.append(
            (
                "CSE",
                CSE_DIRECTORY_SOURCE,
                cse_opener or default_opener,
                cse_url or os.environ.get(CSE_URL_ENV, CSE_URL),
                _parse_cse_directory_rows,
            )
        )

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
            failures[source_name] = str(error) or error.__class__.__name__
            continue
        for row in rows:
            item = _listing_item(
                row,
                exchange=board,
                source=source_name,
                last_verified_at=verified_at,
            )
            listing_id = str(item["listing_id"])
            if listing_id in entries:
                continue
            entries[listing_id] = item
            counts[board] += 1
        if rows:
            sources.append(source_name)

    if cse_export is not None:
        try:
            cse_rows = parse_cse_official_export(cse_export)
            for row in cse_rows:
                item = _listing_item(
                    row,
                    exchange="CSE",
                    source=CSE_EXPORT_SOURCE,
                    last_verified_at=str(row["last_verified_at"]),
                )
                entries[str(item["listing_id"])] = item
            if cse_rows:
                counts["CSE"] = len(cse_rows)
                sources.append(CSE_EXPORT_SOURCE)
        except Exception as error:
            failures[CSE_EXPORT_SOURCE] = str(error) or error.__class__.__name__

    if overlay is not None:
        for row in parse_ca_universe_overlay(overlay):
            item = _listing_item(
                row,
                exchange=str(row["exchange"]),
                source=CSE_OVERLAY_SOURCE,
                last_verified_at=str(row["last_verified_at"]),
            )
            existing = entries.get(str(item["listing_id"]))
            entries[str(item["listing_id"])] = _merge_listing(existing, item)
            if existing is None:
                counts[str(item["exchange"])] = (
                    counts.get(str(item["exchange"]), 0) + 1
                )
        sources.append(CSE_OVERLAY_SOURCE)

    if not entries:
        raise CaUniverseError(
            "All CA universe sources failed; no entries available."
        )

    payload = {
        "updated_at": (
            refreshed_at
            or verified_at
        ),
        "source": sorted(sources),
        "source_failures": failures,
        "counts": counts,
        "items": sorted(
            entries.values(),
            key=lambda item: (item["ticker"], item["exchange"], item["symbol"]),
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
    """Return normalized ticker -> {name, exchange, board} for web fallback."""
    payload = load_ca_universe(path)
    if not payload:
        return {}
    result: Dict[str, Mapping[str, str]] = {}
    for item in payload.get("items") or []:
        ticker = str(item.get("ticker") or "").strip()
        if not ticker:
            continue
        board = str(item.get("board") or item.get("exchange") or "TSX")
        candidate = {
            "name": str(item.get("name") or ticker),
            "exchange": board,
            "board": board,
        }
        _prefer_name_map_entry(result, ticker, candidate)
        for previous_symbol in item.get("previous_symbols") or []:
            previous_ticker = normalize_ca_ticker(str(previous_symbol))
            if previous_ticker:
                _prefer_name_map_entry(result, previous_ticker, candidate)
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
                    records.append(
                        {
                            "ticker": ticker,
                            "symbol": symbol.strip(),
                            "issuer_name": name,
                            "website": _optional_text(
                                instrument.get("website")
                                or result.get("website")
                            ),
                            "investor_relations_url": _optional_text(
                                instrument.get("investorRelationsUrl")
                                or result.get("investorRelationsUrl")
                            ),
                            "sec_cik": _optional_text(
                                instrument.get("secCik")
                                or result.get("secCik")
                            ),
                        }
                    )
        else:
            ticker = normalize_ca_ticker(result_symbol)
            if ticker and result_name:
                records.append(
                    {
                        "ticker": ticker,
                        "symbol": result_symbol.strip(),
                        "issuer_name": result_name,
                        "website": _optional_text(result.get("website")),
                        "investor_relations_url": _optional_text(
                            result.get("investorRelationsUrl")
                        ),
                        "sec_cik": _optional_text(result.get("secCik")),
                    }
                )
    return records


def _parse_cse_directory_rows(
    data: Any,
    board: str,
) -> List[Mapping[str, Any]]:
    """Validate the complete first-party directory used by the CSE website.

    The endpoint contains current and historical securities.  Symbols can be
    recycled, so an active/suspended/halted record wins over an older delisted
    record; older issuer names are retained as aliases.  More than one current
    record for the same symbol is an identity conflict and fails closed.
    """
    if board != "CSE" or not isinstance(data, list):
        raise CaUniverseError("CSE directory response was not a JSON list.")
    if len(data) < 100:
        raise CaUniverseError(
            "CSE all-companies response was unexpectedly truncated."
        )
    allowed_statuses = {
        "Active",
        "Delisted",
        "Halted - Fundamental Change",
        "Suspended",
    }
    grouped: Dict[str, List[Mapping[str, Any]]] = {}
    seen_ids: set[int] = set()
    for raw_row in data:
        if not isinstance(raw_row, Mapping):
            raise CaUniverseError("CSE directory row was not an object.")
        company_id = raw_row.get("id")
        if not isinstance(company_id, int) or company_id <= 0 or company_id in seen_ids:
            raise CaUniverseError("CSE directory row had an invalid or duplicate id.")
        seen_ids.add(company_id)
        symbol = _required_symbol(raw_row.get("symbol"), exchange="CSE")
        issuer_name = _required_text(
            raw_row.get("securityName"), field="securityName"
        )
        status = _required_text(raw_row.get("status"), field="status")
        if status not in allowed_statuses:
            raise CaUniverseError(f"CSE directory returned unknown status {status!r}.")
        slug = _required_text(raw_row.get("slug"), field="slug")
        if any(character not in "abcdefghijklmnopqrstuvwxyz0123456789-" for character in slug):
            raise CaUniverseError("CSE directory row had an invalid profile slug.")
        delisted_at = _optional_text(raw_row.get("delistedDate"))
        if status == "Delisted":
            if not delisted_at:
                raise CaUniverseError("CSE delisted row had no delistedDate.")
            try:
                datetime.fromisoformat(delisted_at)
            except ValueError as error:
                raise CaUniverseError("CSE delistedDate was invalid.") from error
        elif delisted_at:
            raise CaUniverseError("CSE current row unexpectedly had a delistedDate.")
        grouped.setdefault(symbol, []).append(
            {
                "ticker": normalize_ca_ticker(symbol),
                "symbol": symbol,
                "issuer_name": issuer_name,
                "status": status.casefold(),
                "delisted_at": delisted_at,
                "cse_company_id": company_id,
                "source_url": CSE_URL,
                "profile_url": f"https://thecse.com/listings/{slug}/",
            }
        )

    records: List[Mapping[str, Any]] = []
    for symbol, candidates in grouped.items():
        current = [row for row in candidates if row["status"] != "delisted"]
        if len(current) > 1:
            raise CaUniverseError(
                f"CSE directory has conflicting current records for {symbol!r}."
            )
        if current:
            selected = dict(current[0])
        else:
            latest = candidates[0]
            for candidate in candidates[1:]:
                if str(candidate["delisted_at"]) > str(latest["delisted_at"]):
                    latest = candidate
            selected = dict(latest)
        aliases = sorted({
            str(row["issuer_name"])
            for row in candidates
            if row["issuer_name"] != selected["issuer_name"]
        })
        selected["previous_issuer_names"] = aliases
        selected["symbol_history_ambiguous"] = len(candidates) > 1
        records.append(selected)
    return records


def parse_cse_official_export(
    export: Mapping[str, Any],
) -> List[Mapping[str, Any]]:
    """Validate a manually obtained official CSE company export.

    CSE does not currently expose a verified, documented bulk endpoint for
    this application.  Callers must therefore supply the downloaded payload
    along with its first-party ``source_url`` and an offset-aware
    ``exported_at`` timestamp.  Malformed or non-CSE provenance is rejected;
    this function never fetches a URL.

    Expected shape::

        {"source_url": "https://primary.thecse.com/...",
         "exported_at": "2026-08-22T00:00:00+00:00",
         "items": [{"symbol": "ABC", "issuer_name": "Example Inc."}]}
    """
    if not isinstance(export, Mapping):
        raise CaUniverseError("CSE export must be an object.")
    source_url = _validated_cse_url(export.get("source_url"), field="source_url")
    exported_at = _validated_timestamp(
        export.get("exported_at"), field="exported_at"
    )
    rows = export.get("items")
    if not isinstance(rows, list) or not rows:
        raise CaUniverseError("CSE export must contain a non-empty items list.")
    parsed: List[Mapping[str, Any]] = []
    seen: set[str] = set()
    for raw_row in rows:
        if not isinstance(raw_row, Mapping):
            raise CaUniverseError("CSE export item was not an object.")
        symbol = _required_symbol(raw_row.get("symbol"), exchange="CSE")
        if symbol in seen:
            raise CaUniverseError(f"CSE export duplicated symbol {symbol!r}.")
        seen.add(symbol)
        parsed.append(
            {
                "symbol": symbol,
                "ticker": normalize_ca_ticker(symbol),
                "issuer_name": _required_text(
                    raw_row.get("issuer_name") or raw_row.get("name"),
                    field="issuer_name",
                ),
                "website": _optional_url(raw_row.get("website"), field="website"),
                "investor_relations_url": _optional_url(
                    raw_row.get("investor_relations_url"),
                    field="investor_relations_url",
                ),
                "country": _country(raw_row.get("country")),
                "sec_cik": _optional_text(raw_row.get("sec_cik")),
                "source_url": source_url,
                "last_verified_at": exported_at,
                "previous_symbols": _symbol_list(raw_row.get("previous_symbols")),
                "previous_issuer_names": _text_list(
                    raw_row.get("previous_issuer_names"),
                    field="previous_issuer_names",
                ),
            }
        )
    return parsed


def parse_ca_universe_overlay(
    overlay: Mapping[str, Any],
) -> List[Mapping[str, Any]]:
    """Validate local, reviewable listing corrections and rename aliases.

    An overlay may add a CSE listing from an official export or enrich any
    existing exchange listing.  It is explicitly labelled as configuration
    provenance rather than being represented as a live exchange response.
    """
    if not isinstance(overlay, Mapping):
        raise CaUniverseError("CA universe overlay must be an object.")
    rows = overlay.get("items")
    if not isinstance(rows, list):
        raise CaUniverseError("CA universe overlay must contain an items list.")
    default_verified_at = overlay.get("last_verified_at")
    parsed: List[Mapping[str, Any]] = []
    for raw_row in rows:
        if not isinstance(raw_row, Mapping):
            raise CaUniverseError("CA universe overlay item was not an object.")
        exchange = _required_text(raw_row.get("exchange"), field="exchange").upper()
        if exchange not in _EXCHANGE_PRIORITY:
            raise CaUniverseError(f"Unsupported CA overlay exchange {exchange!r}.")
        symbol = _required_symbol(raw_row.get("symbol"), exchange=exchange)
        parsed.append(
            {
                "symbol": symbol,
                "ticker": normalize_ca_ticker(symbol),
                "exchange": exchange,
                "issuer_name": _required_text(
                    raw_row.get("issuer_name") or raw_row.get("name"),
                    field="issuer_name",
                ),
                "website": _optional_url(raw_row.get("website"), field="website"),
                "investor_relations_url": _optional_url(
                    raw_row.get("investor_relations_url"),
                    field="investor_relations_url",
                ),
                "country": _country(raw_row.get("country")),
                "sec_cik": _optional_text(raw_row.get("sec_cik")),
                "last_verified_at": _validated_timestamp(
                    raw_row.get("last_verified_at") or default_verified_at,
                    field="last_verified_at",
                ),
                "previous_symbols": _symbol_list(raw_row.get("previous_symbols")),
                "previous_issuer_names": _text_list(
                    raw_row.get("previous_issuer_names"),
                    field="previous_issuer_names",
                ),
            }
        )
    return parsed


class _CseDocumentParser(HTMLParser):
    """Small offline extractor for public CSE profile/bulletin HTML."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.meta: Dict[str, str] = {}
        self.links: List[Mapping[str, str]] = []
        self.times: List[str] = []
        self._heading_depth = 0
        self._heading_parts: List[str] = []
        self.headings: List[str] = []
        self._link_href: Optional[str] = None
        self._link_parts: List[str] = []

    def handle_starttag(self, tag: str, attrs: List[tuple[str, Optional[str]]]) -> None:
        attributes = {key.lower(): value or "" for key, value in attrs}
        if tag == "meta":
            key = (attributes.get("property") or attributes.get("name") or "").lower()
            content = attributes.get("content", "").strip()
            if key and content:
                self.meta[key] = content
        elif tag == "time" and attributes.get("datetime"):
            self.times.append(attributes["datetime"].strip())
        elif tag in {"h1", "h2"}:
            self._heading_depth += 1
        elif tag == "a" and attributes.get("href"):
            self._link_href = attributes["href"].strip()
            self._link_parts = []

    def handle_data(self, data: str) -> None:
        if self._heading_depth:
            self._heading_parts.append(data)
        if self._link_href is not None:
            self._link_parts.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag in {"h1", "h2"} and self._heading_depth:
            self._heading_depth -= 1
            if not self._heading_depth:
                heading = " ".join("".join(self._heading_parts).split())
                if heading:
                    self.headings.append(heading)
                self._heading_parts = []
        elif tag == "a" and self._link_href is not None:
            self.links.append(
                {
                    "href": self._link_href,
                    "text": " ".join("".join(self._link_parts).split()),
                }
            )
            self._link_href = None
            self._link_parts = []


def parse_cse_profile_html(
    html: str,
    *,
    source_url: str,
    last_verified_at: str,
) -> Mapping[str, Any]:
    """Parse an already obtained CSE issuer profile without any HTTP call."""
    _validated_cse_url(source_url, field="source_url")
    parser = _parse_cse_html(html)
    title = parser.meta.get("og:title") or (parser.headings[0] if parser.headings else "")
    issuer_name, symbol = _cse_title_identity(title)
    website, investor_relations_url = _profile_links(parser.links)
    return _listing_item(
        {
            "symbol": symbol,
            "issuer_name": issuer_name,
            "website": website,
            "investor_relations_url": investor_relations_url,
            "source_url": source_url,
        },
        exchange="CSE",
        source="cse_profile_offline_html",
        last_verified_at=_validated_timestamp(
            last_verified_at, field="last_verified_at"
        ),
    )


def parse_cse_bulletin_html(
    html: str,
    *,
    source_url: str,
    last_verified_at: str,
) -> Mapping[str, Any]:
    """Parse an already obtained CSE halt/resume bulletin, fail closed."""
    canonical_url = _validated_cse_url(source_url, field="source_url")
    if "/bulletin/" not in urlsplit(canonical_url).path:
        raise CaUniverseError("CSE bulletin URL must use the /bulletin/ path.")
    parser = _parse_cse_html(html)
    title = parser.meta.get("og:title") or (parser.headings[0] if parser.headings else "")
    issuer_name, symbol = _cse_title_identity(title)
    event_type = _cse_bulletin_event(title)
    if not parser.times:
        raise CaUniverseError("CSE bulletin had no machine-readable publication time.")
    return {
        "issuer_name": issuer_name,
        "symbol": symbol,
        "ticker": normalize_ca_ticker(symbol),
        "exchange": "CSE",
        "country": "CA",
        "event_type": event_type,
        "published_at": _validated_timestamp(parser.times[0], field="published_at"),
        "source": "cse_bulletin_offline_html",
        "source_url": canonical_url,
        "last_verified_at": _validated_timestamp(
            last_verified_at, field="last_verified_at"
        ),
    }


def _listing_item(
    row: Mapping[str, Any],
    *,
    exchange: str,
    source: str,
    last_verified_at: str,
) -> Mapping[str, Any]:
    """Normalize a source record into the cache's stable listing shape."""
    normalized_exchange = _required_text(exchange, field="exchange").upper()
    symbol = _required_symbol(
        row.get("symbol") or row.get("ticker"), exchange=normalized_exchange
    )
    ticker = normalize_ca_ticker(str(row.get("ticker") or symbol))
    if not ticker:
        raise CaUniverseError(f"{normalized_exchange} listing had no ticker.")
    issuer_name = _required_text(
        row.get("issuer_name") or row.get("name"), field="issuer_name"
    )
    previous_symbols = _symbol_list(row.get("previous_symbols"))
    previous_issuer_names = _text_list(
        row.get("previous_issuer_names"), field="previous_issuer_names"
    )
    return {
        # Legacy keys remain for all existing cache consumers.
        "ticker": ticker,
        "name": issuer_name,
        "board": normalized_exchange,
        "status": str(row.get("status") or "active"),
        "delisted_at": _optional_text(row.get("delisted_at")),
        # Listing/provenance contract.
        "listing_id": f"{normalized_exchange}:{symbol}",
        "issuer_name": issuer_name,
        "symbol": symbol,
        "exchange": normalized_exchange,
        "website": _optional_url(row.get("website"), field="website"),
        "investor_relations_url": _optional_url(
            row.get("investor_relations_url"), field="investor_relations_url"
        ),
        "country": _country(row.get("country")),
        "sec_cik": _optional_text(row.get("sec_cik")),
        "source": _required_text(source, field="source"),
        "source_url": _optional_url(row.get("source_url"), field="source_url"),
        "profile_url": _optional_url(row.get("profile_url"), field="profile_url"),
        "cse_company_id": row.get("cse_company_id"),
        "symbol_history_ambiguous": bool(row.get("symbol_history_ambiguous")),
        "last_verified_at": _validated_timestamp(
            last_verified_at, field="last_verified_at"
        ),
        "previous_symbols": previous_symbols,
        "previous_issuer_names": previous_issuer_names,
    }


def _merge_listing(
    existing: Optional[Mapping[str, Any]],
    overlay: Mapping[str, Any],
) -> Mapping[str, Any]:
    """Apply a reviewed overlay without discarding live-listing identity."""
    if existing is None:
        return overlay
    merged = dict(existing)
    # Overlay data is reviewable correction metadata, not a replacement for
    # a directory's listing status.  Only explicitly supplied non-empty values
    # may enrich it, while source records retain an audit trail.
    for field in (
        "issuer_name",
        "name",
        "website",
        "investor_relations_url",
        "country",
        "sec_cik",
        "previous_symbols",
        "previous_issuer_names",
    ):
        value = overlay.get(field)
        if value not in (None, "", []):
            merged[field] = value
    merged["name"] = str(merged["issuer_name"])
    merged["overlay_source"] = str(overlay["source"])
    merged["overlay_last_verified_at"] = str(overlay["last_verified_at"])
    return merged


def _prefer_name_map_entry(
    result: Dict[str, Mapping[str, str]],
    ticker: str,
    candidate: Mapping[str, str],
) -> None:
    current = result.get(ticker)
    if current is None:
        result[ticker] = candidate
        return
    current_priority = _EXCHANGE_PRIORITY.get(current["exchange"], 99)
    candidate_priority = _EXCHANGE_PRIORITY.get(candidate["exchange"], 99)
    if candidate_priority < current_priority:
        result[ticker] = candidate


def _parse_cse_html(html: str) -> _CseDocumentParser:
    if not isinstance(html, str) or not html.strip():
        raise CaUniverseError("CSE offline HTML was empty.")
    parser = _CseDocumentParser()
    try:
        parser.feed(html)
        parser.close()
    except Exception as error:
        raise CaUniverseError("CSE offline HTML could not be parsed.") from error
    return parser


def _cse_title_identity(title: str) -> tuple[str, str]:
    clean_title = " ".join(str(title or "").split())
    if not clean_title:
        raise CaUniverseError("CSE document had no title or heading.")
    import re

    match = re.search(r"\((?:CSE\s*:\s*)?([A-Za-z0-9.\-]+)\)\s*$", clean_title)
    if match is None:
        raise CaUniverseError("CSE document title had no parenthesized symbol.")
    symbol = _required_symbol(match.group(1), exchange="CSE")
    issuer_name = clean_title[: match.start()].strip(" -–—")
    # Bulletin titles may start with an action.  CSE pages commonly use an
    # em-dash to separate it from the issuer; otherwise the title is too
    # ambiguous to turn into issuer provenance automatically.
    if " - " in issuer_name:
        issuer_name = issuer_name.rsplit(" - ", 1)[-1].strip()
    elif " – " in issuer_name:
        issuer_name = issuer_name.rsplit(" – ", 1)[-1].strip()
    elif " — " in issuer_name:
        issuer_name = issuer_name.rsplit(" — ", 1)[-1].strip()
    return _required_text(issuer_name, field="issuer_name"), symbol


def _profile_links(
    links: Iterable[Mapping[str, str]],
) -> tuple[Optional[str], Optional[str]]:
    website: Optional[str] = None
    investor_relations_url: Optional[str] = None
    for link in links:
        text = str(link.get("text") or "").lower()
        href = _optional_url(link.get("href"), field="profile link")
        if href is None:
            continue
        if "investor" in text or "ir" == text.strip():
            investor_relations_url = href
        elif "website" in text or "web site" in text:
            website = href
    return website, investor_relations_url


def _cse_bulletin_event(title: str) -> str:
    normalized = title.lower()
    if "reinstatement" in normalized or "resumption" in normalized or "resume trading" in normalized:
        return "resume"
    if "halt" in normalized or "suspension" in normalized:
        return "halt"
    raise CaUniverseError("CSE bulletin was not a halt or resume event.")


def _validated_cse_url(value: Any, *, field: str) -> str:
    url = _optional_url(value, field=field)
    host = urlsplit(url or "").hostname or ""
    if host.lower() not in _CSE_HOSTS:
        raise CaUniverseError(f"{field} must be a first-party CSE HTTPS URL.")
    return str(url)


def _required_symbol(value: Any, *, exchange: str) -> str:
    symbol = str(value or "").strip().upper()
    if not symbol or normalize_ca_ticker(symbol) == "":
        raise CaUniverseError(f"{exchange} listing had an invalid symbol.")
    return symbol


def _required_text(value: Any, *, field: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise CaUniverseError(f"{field} was required.")
    return text


def _optional_text(value: Any) -> Optional[str]:
    text = str(value or "").strip()
    return text or None


def _optional_url(value: Any, *, field: str) -> Optional[str]:
    url = _optional_text(value)
    if url is None:
        return None
    parsed = urlsplit(url)
    if parsed.scheme != "https" or not parsed.hostname:
        raise CaUniverseError(f"{field} must be an absolute HTTPS URL.")
    return url


def _country(value: Any) -> str:
    country = _optional_text(value)
    if country is None:
        return "CA"
    if country.upper() not in {"CA", "CANADA"}:
        raise CaUniverseError("CA universe country must be CA.")
    return "CA"


def _symbol_list(value: Any) -> List[str]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise CaUniverseError("previous_symbols must be a list.")
    parsed = [_required_symbol(item, exchange="CA") for item in value]
    if len(set(parsed)) != len(parsed):
        raise CaUniverseError("previous_symbols contained duplicates.")
    return parsed


def _text_list(value: Any, *, field: str) -> List[str]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise CaUniverseError(f"{field} must be a list.")
    parsed = [_required_text(item, field=field) for item in value]
    if len(set(parsed)) != len(parsed):
        raise CaUniverseError(f"{field} contained duplicates.")
    return parsed


def _validated_timestamp(value: Any, *, field: str) -> str:
    text = _required_text(value, field=field)
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as error:
        raise CaUniverseError(f"{field} was not an ISO-8601 timestamp.") from error
    if parsed.tzinfo is None:
        raise CaUniverseError(f"{field} must include a timezone offset.")
    return parsed.isoformat()


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


def _optional_json_mapping_from_env(name: str) -> Optional[Mapping[str, Any]]:
    raw_path = os.environ.get(name, "").strip()
    if not raw_path:
        return None
    try:
        with Path(raw_path).open("r", encoding="utf-8") as handle:
            payload = json.load(handle)
    except (OSError, json.JSONDecodeError) as error:
        raise CaUniverseError(f"{name} could not be loaded: {error}") from error
    if not isinstance(payload, Mapping):
        raise CaUniverseError(f"{name} must contain a JSON object.")
    return payload
