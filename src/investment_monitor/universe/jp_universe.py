"""Official partial Tokyo Stock Exchange listed-security universe.

JPX publishes a free English XLS containing the previous month-end TSE
listed issues.  This module polls the fixed official URL, validates the full
workbook, classifies equities and listed products, and atomically caches the
result.  Daily polling is useful even though the upstream file is monthly:
ETag/Last-Modified and SHA-256 checks avoid rewriting an unchanged snapshot.

This is not a complete Japanese national universe.  Cboe Japan, Japannext,
same-month listing changes, and historical/delisted issues are outside the
free monthly file, so country coverage remains partial.
"""

from __future__ import annotations

from datetime import date, datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import time
from typing import Any, Callable, Dict, List, Mapping, Optional
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

import xlrd  # type: ignore[import-untyped]

from ..sources.jp_news.symbols import normalize_jp_ticker

DEFAULT_CACHE_PATH = ".cache/investment_monitor/jp_universe.json"
SCHEMA = "jp_universe/v1"
DIRECTORY_URL = (
    "https://www.jpx.co.jp/english/markets/statistics-equities/misc/"
    "tvdivq0000001vg2-att/data_e.xls"
)
DIRECTORY_URL_ENV = "JP_UNIVERSE_DIRECTORY_URL"
DEFAULT_USER_AGENT = "InvestmentMonitor/0.1 (official JPX monthly directory)"
RETRYABLE_HTTP_STATUS = frozenset({500, 502, 503, 504})
HEADERS = (
    "Effective Date",
    "Local Code",
    "Name (English)",
    "Section/Products",
    "33 Sector(Code)",
    "33 Sector(name)",
    "17 Sector(Code)",
    "17 Sector(name)",
    "Size Code (New Index Series)",
    "Size (New Index Series)",
)
# JPX normally uses four-character codes, including the new ``123A`` form.
# A small official set of class/preferred shares uses five numeric characters
# (for example 25935); preserving all five is required for exact identity.
_CODE = re.compile(r"(?:[0-9]{4,5}|[0-9]{3}[A-Z])")
_EQUITY_SECTIONS = frozenset(
    {
        "Prime Market (Domestic)",
        "Prime Market(Foreign)",
        "Standard Market(Domestic)",
        "Standard Market(Foreign)",
        "Growth Market(Domestic)",
        "Growth Market (Foreign)",
        "PRO Market",
    }
)
_ETF_SECTION = "ETFs/ ETNs"
_LISTED_FUND_SECTION = (
    "REIT, Venture Funds, Country Funds and Infrastructure Funds"
)
_CONTRIBUTION_SECTION = "Equity Contribution Securities"
_KNOWN_SECTIONS = _EQUITY_SECTIONS | {
    _ETF_SECTION,
    _LISTED_FUND_SECTION,
    _CONTRIBUTION_SECTION,
}
_COUNT_KEYS = frozenset(
    {
        "equity",
        "etf_etn",
        "listed_fund",
        "equity_contribution_security",
    }
)
_SOURCE = ["jpx_month_end_listed_issues"]
_COVERAGE = "official_partial_tse_previous_month_end"


class JpUniverseError(RuntimeError):
    """Raised when the JPX official workbook cannot be validated safely."""


def parse_jp_universe_xls(content: bytes) -> Mapping[str, Any]:
    """Parse and classify the complete official JPX workbook."""
    if not content:
        raise JpUniverseError("JPX listed-issues workbook is empty")
    try:
        workbook = xlrd.open_workbook(file_contents=content)
    except Exception as error:  # xlrd may surface low-level OLE/BIFF errors
        raise JpUniverseError("JPX listed-issues workbook is not a valid XLS") from error
    if workbook.sheet_names() != ["Sheet1"]:
        raise JpUniverseError("JPX listed-issues workbook sheet contract changed")
    sheet = workbook.sheet_by_index(0)
    if sheet.nrows < 2 or sheet.ncols != len(HEADERS):
        raise JpUniverseError("JPX listed-issues workbook is empty or changed")
    actual_headers = tuple(_text(sheet.cell_value(0, index)) for index in range(sheet.ncols))
    if actual_headers != HEADERS:
        raise JpUniverseError("JPX listed-issues workbook headers changed")

    items: List[Mapping[str, Any]] = []
    seen_codes: set[str] = set()
    effective_dates: set[str] = set()
    counts: Dict[str, int] = {
        "equity": 0,
        "etf_etn": 0,
        "listed_fund": 0,
        "equity_contribution_security": 0,
    }
    for row_index in range(1, sheet.nrows):
        values = [sheet.cell_value(row_index, column) for column in range(sheet.ncols)]
        effective_date = _effective_date(values[0])
        ticker = _local_code(values[1])
        name = _text(values[2])
        section = _text(values[3])
        if not name or section not in _KNOWN_SECTIONS:
            raise JpUniverseError(
                f"JPX listed-issues row {row_index + 1} has an unknown product"
            )
        if ticker in seen_codes:
            raise JpUniverseError(f"JPX listed-issues workbook repeated code {ticker}")
        seen_codes.add(ticker)
        effective_dates.add(effective_date)
        instrument_type = _instrument_type(section)
        counts[instrument_type] += 1
        items.append(
            {
                "ticker": ticker,
                "name": name,
                "exchange": "Tokyo Stock Exchange",
                "board": section,
                "section_products": section,
                "instrument_type": instrument_type,
                "effective_date": effective_date,
                "sector_33_code": _optional_code(values[4]),
                "sector_33_name": _optional_text(values[5]),
                "sector_17_code": _optional_code(values[6]),
                "sector_17_name": _optional_text(values[7]),
                "size_code": _optional_code(values[8]),
                "size_name": _optional_text(values[9]),
                "status": "active_at_month_end",
                "source": "jpx_month_end_listed_issues",
                "official_listing_url": (
                    "https://www.jpx.co.jp/english/markets/"
                    "statistics-equities/misc/01.html"
                ),
            }
        )
    if len(effective_dates) != 1:
        raise JpUniverseError("JPX workbook contains mixed effective dates")
    return {
        "source_effective_date": next(iter(effective_dates)),
        "counts_by_type": counts,
        "items": sorted(items, key=lambda item: str(item["ticker"])),
    }


def load_jp_universe(path: Optional[Path] = None) -> Optional[Mapping[str, Any]]:
    """Load only a self-consistent cache written by this module."""
    payload = _load_raw_cache(_cache_path(path))
    if not payload:
        return None
    try:
        recorded_minimum = int(payload.get("validated_minimum_items") or 0)
    except (TypeError, ValueError):
        return None
    if recorded_minimum <= 0 or not _cache_is_reusable(
        payload,
        source_url=str(payload.get("source_url") or ""),
        minimum_items=recorded_minimum,
    ):
        return None
    return payload


def refresh_jp_universe(
    *,
    path: Optional[Path] = None,
    opener: Callable[..., Any] = urlopen,
    url: Optional[str] = None,
    refreshed_at: Optional[str] = None,
    minimum_items: int = 3500,
    timeout: float = 30.0,
    max_retries: int = 1,
    sleeper: Callable[[float], None] = time.sleep,
) -> Mapping[str, Any]:
    """Poll the official workbook and replace the cache only after validation."""
    if minimum_items <= 0 or timeout <= 0 or max_retries < 0:
        raise ValueError("JPX refresh limits must be valid")
    cache_path = _cache_path(path)
    source_url = url or os.environ.get(DIRECTORY_URL_ENV, DIRECTORY_URL)
    raw_prior = _load_raw_cache(cache_path)
    prior = (
        raw_prior
        if raw_prior
        and _cache_is_reusable(
            raw_prior,
            source_url=source_url,
            minimum_items=minimum_items,
        )
        else None
    )
    headers = {
        "User-Agent": DEFAULT_USER_AGENT,
        "Accept": "application/vnd.ms-excel,application/octet-stream",
    }
    prior_http = prior.get("http_validators") if isinstance(prior, Mapping) else None
    if isinstance(prior_http, Mapping):
        etag = str(prior_http.get("etag") or "")
        last_modified = str(prior_http.get("last_modified") or "")
        if etag:
            headers["If-None-Match"] = etag
        if last_modified:
            headers["If-Modified-Since"] = last_modified
    request = Request(source_url, headers=headers)
    response_headers: Mapping[str, Any] = {}
    content: Optional[bytes] = None
    for attempt in range(max_retries + 1):
        try:
            with opener(request, timeout=timeout) as response:
                content = response.read()
                response_headers = getattr(response, "headers", {})
            break
        except HTTPError as error:
            if error.code == 304:
                if prior:
                    return prior
                raise JpUniverseError(
                    "JPX returned HTTP 304 without a reusable validated cache"
                ) from error
            if error.code not in RETRYABLE_HTTP_STATUS or attempt == max_retries:
                raise JpUniverseError(
                    f"JPX listed-issues request failed with HTTP {error.code}"
                ) from error
        except (URLError, TimeoutError) as error:
            if attempt == max_retries:
                raise JpUniverseError(
                    "JPX listed-issues request failed after retries"
                ) from error
        sleeper(0.5 * (2**attempt))
    if content is None:
        raise JpUniverseError("JPX listed-issues request returned no content")
    digest = hashlib.sha256(content).hexdigest()
    if prior and digest == str(prior.get("content_sha256") or ""):
        return prior

    parsed = parse_jp_universe_xls(content)
    items = [
        {**item, "source_url": source_url}
        for item in parsed["items"]
    ]
    if len(items) < minimum_items:
        raise JpUniverseError(
            f"JPX listed-issues workbook is suspiciously small: {len(items)}"
        )
    effective_date = date.fromisoformat(str(parsed["source_effective_date"]))
    if prior and prior.get("source_effective_date"):
        try:
            prior_date = date.fromisoformat(str(prior["source_effective_date"]))
        except ValueError as error:
            raise JpUniverseError("Existing JPX cache effective date is invalid") from error
        if effective_date < prior_date:
            raise JpUniverseError("JPX source effective date moved backwards")
    payload: Mapping[str, Any] = {
        "schema": SCHEMA,
        "updated_at": refreshed_at or datetime.now(timezone.utc).isoformat(),
        "source_effective_date": effective_date.isoformat(),
        "source": _SOURCE,
        "source_url": source_url,
        "content_sha256": digest,
        "http_validators": {
            "etag": _header(response_headers, "ETag"),
            "last_modified": _header(response_headers, "Last-Modified"),
        },
        "coverage": _COVERAGE,
        "validated_minimum_items": minimum_items,
        "coverage_boundary": {
            "included": [
                "TSE Prime, Standard, Growth and PRO Market equities",
                "TSE foreign equities",
                "TSE ETFs/ETNs and listed funds",
                "TSE equity contribution securities",
            ],
            "not_covered": [
                "Cboe Japan",
                "Japannext PTS",
                "changes after the reported month end",
                "historical and delisted securities",
                "ETF issuer disclosures",
            ],
            "daily_poll_monthly_source": True,
        },
        "counts": {"total": len(items)},
        "counts_by_type": parsed["counts_by_type"],
        "items": items,
    }
    _atomic_write(cache_path, payload)
    return payload


def jp_universe_name_map(
    path: Optional[Path] = None,
) -> Mapping[str, Mapping[str, str]]:
    payload = load_jp_universe(path)
    if not payload:
        return {}
    result: Dict[str, Mapping[str, str]] = {}
    for item in payload.get("items") or []:
        if not isinstance(item, Mapping):
            continue
        ticker = normalize_jp_ticker(str(item.get("ticker") or ""))
        if not ticker:
            continue
        result[ticker] = {
            "name": str(item.get("name") or ticker),
            "exchange": str(item.get("exchange") or "Tokyo Stock Exchange"),
            "board": str(item.get("board") or "Tokyo Stock Exchange"),
            "instrument_type": str(item.get("instrument_type") or "equity"),
        }
    return result


def search_jp_universe(
    query: str,
    path: Optional[Path] = None,
) -> List[Mapping[str, Any]]:
    payload = load_jp_universe(path)
    needle = _text(query).casefold()
    if not payload or not needle:
        return []
    matches: List[Mapping[str, Any]] = []
    for item in payload.get("items") or []:
        if not isinstance(item, Mapping):
            continue
        haystack = " ".join(
            str(item.get(field) or "")
            for field in (
                "ticker", "name", "board", "instrument_type",
                "sector_33_name", "sector_17_name",
            )
        ).casefold()
        if needle in haystack:
            matches.append(dict(item))
        if len(matches) >= 50:
            break
    return matches


def _effective_date(value: Any) -> str:
    if isinstance(value, float) and value.is_integer():
        text = str(int(value))
    else:
        text = _text(value)
    if not re.fullmatch(r"[0-9]{8}", text):
        raise JpUniverseError("JPX workbook contains an invalid effective date")
    try:
        return datetime.strptime(text, "%Y%m%d").date().isoformat()
    except ValueError as error:
        raise JpUniverseError("JPX workbook contains an invalid effective date") from error


def _local_code(value: Any) -> str:
    if isinstance(value, float) and value.is_integer():
        raw = str(int(value))
    else:
        raw = _text(value).upper()
    code = str(normalize_jp_ticker(raw))
    if not _CODE.fullmatch(code):
        raise JpUniverseError(f"JPX workbook contains invalid local code {raw!r}")
    return code


def _instrument_type(section: str) -> str:
    if section in _EQUITY_SECTIONS:
        return "equity"
    if section == _ETF_SECTION:
        return "etf_etn"
    if section == _LISTED_FUND_SECTION:
        return "listed_fund"
    if section == _CONTRIBUTION_SECTION:
        return "equity_contribution_security"
    raise JpUniverseError(f"Unknown JPX Section/Products value {section!r}")


def _optional_code(value: Any) -> str:
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    text = _text(value)
    return "" if text == "-" else text


def _optional_text(value: Any) -> str:
    text = _text(value)
    return "" if text == "-" else text


def _text(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _header(headers: Mapping[str, Any], name: str) -> str:
    getter = getattr(headers, "get", None)
    if not callable(getter):
        return ""
    return str(getter(name) or getter(name.lower()) or "")


def _load_raw_cache(path: Path) -> Optional[Mapping[str, Any]]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, Mapping) else None


def _cache_is_reusable(
    payload: Mapping[str, Any],
    *,
    source_url: str,
    minimum_items: int,
) -> bool:
    """Validate identity, counts and item rows before conditional reuse."""
    if (
        payload.get("schema") != SCHEMA
        or payload.get("source") != _SOURCE
        or payload.get("coverage") != _COVERAGE
        or not source_url
        or payload.get("source_url") != source_url
        or not re.fullmatch(r"[0-9a-f]{64}", str(payload.get("content_sha256") or ""))
    ):
        return False
    try:
        date.fromisoformat(str(payload["source_effective_date"]))
        recorded_minimum = int(payload["validated_minimum_items"])
    except (KeyError, TypeError, ValueError):
        return False
    if recorded_minimum <= 0:
        return False
    items = payload.get("items")
    counts = payload.get("counts")
    counts_by_type = payload.get("counts_by_type")
    if (
        not isinstance(items, list)
        or len(items) < minimum_items
        or not isinstance(counts, Mapping)
        or counts.get("total") != len(items)
        or not isinstance(counts_by_type, Mapping)
        or set(counts_by_type) != _COUNT_KEYS
    ):
        return False
    actual_counts = {key: 0 for key in _COUNT_KEYS}
    seen: set[str] = set()
    effective_date = str(payload["source_effective_date"])
    for item in items:
        if not isinstance(item, Mapping):
            return False
        ticker = str(item.get("ticker") or "")
        instrument_type = str(item.get("instrument_type") or "")
        if (
            not _CODE.fullmatch(ticker)
            or ticker in seen
            or not str(item.get("name") or "").strip()
            or instrument_type not in _COUNT_KEYS
            or item.get("effective_date") != effective_date
            or item.get("source") != "jpx_month_end_listed_issues"
            or item.get("source_url") != source_url
        ):
            return False
        seen.add(ticker)
        actual_counts[instrument_type] += 1
    try:
        declared_counts = {key: int(counts_by_type[key]) for key in _COUNT_KEYS}
    except (KeyError, TypeError, ValueError):
        return False
    return actual_counts == declared_counts and sum(declared_counts.values()) == len(items)


def _cache_path(path: Optional[Path]) -> Path:
    return Path(path or os.environ.get("JP_UNIVERSE_CACHE_PATH", DEFAULT_CACHE_PATH))


def _atomic_write(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    temporary.replace(path)


__all__ = [
    "DIRECTORY_URL",
    "HEADERS",
    "JpUniverseError",
    "SCHEMA",
    "jp_universe_name_map",
    "load_jp_universe",
    "parse_jp_universe_xls",
    "refresh_jp_universe",
    "search_jp_universe",
]
