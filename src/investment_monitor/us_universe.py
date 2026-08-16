# -*- coding: utf-8 -*-
"""US exchange-listed stock/ETF universe with optional SEC CIK enrichment.

The authoritative breadth inputs are Nasdaq Trader's key-free Symbol Directory
files. ``nasdaqlisted.txt`` covers Nasdaq-listed issues and
``otherlisted.txt`` covers issues listed on NYSE, NYSE American, NYSE Arca,
Cboe/BATS and IEX. Both publish an explicit ETF flag and a file-creation
footer. Field definitions:
https://www.nasdaqtrader.com/trader.aspx?id=symboldirdefs

The SEC company-ticker JSON remains an enrichment source for CIK values; it
never overwrites the directory's exchange or ETF classification. OTC/Pink
completeness is not established, so this remains a partial US country
universe. The cache never flows directly into ``information_items``.
"""

from __future__ import annotations

import csv
import gzip
import io
import json
import logging
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Mapping, Optional
from urllib.request import Request, urlopen

LOGGER = logging.getLogger(__name__)

DEFAULT_CACHE_PATH = ".cache/investment_monitor/us_universe.json"
DEFAULT_SEC_URL = "https://www.sec.gov/files/company_tickers_exchange.json"
DEFAULT_URL = DEFAULT_SEC_URL  # Backward-compatible name for callers.
DEFAULT_NASDAQ_LISTED_URL = (
    "https://www.nasdaqtrader.com/dynamic/SymDir/nasdaqlisted.txt"
)
DEFAULT_OTHER_LISTED_URL = (
    "https://www.nasdaqtrader.com/dynamic/SymDir/otherlisted.txt"
)
DEFAULT_USER_AGENT = "InvestmentMonitor research@example.com"

OTHER_EXCHANGE_NAMES = {
    "A": "NYSE American",
    "N": "NYSE",
    "P": "NYSE Arca",
    "Z": "Cboe BZX",
    "V": "IEX",
}


class UsUniverseError(RuntimeError):
    """Raised when an authoritative US symbol directory cannot be refreshed."""


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


def _fetch_bytes(
    source_url: str,
    *,
    opener: Callable[..., Any],
    accept: str,
) -> bytes:
    request = Request(
        source_url,
        headers={
            "User-Agent": os.environ.get(
                "US_UNIVERSE_USER_AGENT", DEFAULT_USER_AGENT
            ),
            "Accept": accept,
        },
    )
    with opener(request, timeout=20) as response:
        raw = response.read()
        if response.headers.get("Content-Encoding") == "gzip":
            raw = gzip.decompress(raw)
        return raw


def _parse_symbol_directory(raw: bytes, *, kind: str) -> Dict[str, Dict[str, Any]]:
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError as error:
        raise UsUniverseError(f"{kind} symbol directory is not UTF-8") from error
    nonblank_lines = [line for line in text.splitlines() if line.strip()]
    if not nonblank_lines or not re.fullmatch(
        r"File Creation Time: \d{10}:\d{2}\|.*", nonblank_lines[-1]
    ):
        raise UsUniverseError(
            f"{kind} symbol directory is truncated or missing its creation footer"
        )
    reader = csv.DictReader(io.StringIO(text), delimiter="|")
    fields = set(reader.fieldnames or [])
    if kind == "nasdaq":
        required = {"Symbol", "Security Name", "Test Issue", "ETF"}
        symbol_field = "Symbol"
    elif kind == "other":
        required = {
            "ACT Symbol", "Security Name", "Exchange", "Test Issue", "ETF"
        }
        symbol_field = "ACT Symbol"
    else:
        raise ValueError("unknown US symbol-directory kind")
    if not required.issubset(fields):
        missing = ", ".join(sorted(required - fields))
        raise UsUniverseError(f"{kind} symbol directory missing fields: {missing}")

    entries: Dict[str, Dict[str, Any]] = {}
    for row in reader:
        ticker = str(row.get(symbol_field) or "").strip().upper()
        if ticker.startswith("FILE CREATION TIME"):
            continue
        if not ticker:
            raise UsUniverseError(f"{kind} symbol directory has a blank symbol row")
        if None in row or any(row.get(field) is None for field in required):
            raise UsUniverseError(f"{kind} symbol directory has a malformed row")
        test_issue = str(row.get("Test Issue") or "").strip().upper()
        etf_flag = str(row.get("ETF") or "").strip().upper()
        if test_issue not in {"Y", "N"} or etf_flag not in {"Y", "N"}:
            raise UsUniverseError(
                f"{kind} symbol directory has an invalid Y/N flag for {ticker}"
            )
        if test_issue != "N":
            continue
        if kind == "nasdaq":
            exchange = "Nasdaq"
            raw_exchange = str(row.get("Market Category") or "").strip()
            source = "nasdaq_trader_nasdaqlisted"
        else:
            raw_exchange = str(row.get("Exchange") or "").strip().upper()
            exchange = OTHER_EXCHANGE_NAMES.get(raw_exchange, raw_exchange)
            if not exchange:
                raise UsUniverseError(
                    f"other symbol directory has no exchange for {ticker}"
                )
            source = "nasdaq_trader_otherlisted"
        entries[ticker] = {
            "ticker": ticker,
            "name": str(row.get("Security Name") or ticker).strip(),
            "exchange": exchange,
            "exchange_code": raw_exchange,
            "cik": "",
            "instrument_type": "etf" if etf_flag == "Y" else "stock",
            "universe_source": source,
            "source_tier": "official",
        }
    if not entries:
        raise UsUniverseError(f"{kind} symbol directory returned no usable entries")
    return entries


def _sec_enrichment(raw: bytes) -> Dict[str, Dict[str, str]]:
    payload = json.loads(raw.decode("utf-8"))
    fields = list(payload.get("fields") or [])
    if not {"cik", "name", "ticker", "exchange"}.issubset(fields):
        raise ValueError("SEC ticker payload is missing required fields")
    result: Dict[str, Dict[str, str]] = {}
    for row in payload.get("data") or []:
        record = dict(zip(fields, row))
        ticker = str(record.get("ticker") or "").strip().upper()
        if ticker:
            result[ticker] = {
                "cik": str(record.get("cik") or ""),
                "name": str(record.get("name") or ""),
            }
    return result


def refresh_us_universe(
    *,
    path: Optional[Path] = None,
    opener: Optional[Callable[..., Any]] = None,
    url: Optional[str] = None,
    nasdaq_url: Optional[str] = None,
    other_url: Optional[str] = None,
    refreshed_at: Optional[str] = None,
) -> Mapping[str, Any]:
    """Refresh official exchange-listed issues, then add optional SEC CIKs."""
    cache_path = _cache_path(path)
    open_url = opener or urlopen
    sec_url = url or os.environ.get("US_UNIVERSE_URL", DEFAULT_SEC_URL)
    nasdaq_source_url = nasdaq_url or os.environ.get(
        "US_NASDAQ_LISTED_URL", DEFAULT_NASDAQ_LISTED_URL
    )
    other_source_url = other_url or os.environ.get(
        "US_OTHER_LISTED_URL", DEFAULT_OTHER_LISTED_URL
    )
    try:
        nasdaq_entries = _parse_symbol_directory(
            _fetch_bytes(nasdaq_source_url, opener=open_url, accept="text/plain"),
            kind="nasdaq",
        )
        other_entries = _parse_symbol_directory(
            _fetch_bytes(other_source_url, opener=open_url, accept="text/plain"),
            kind="other",
        )
    except Exception as error:  # noqa: BLE001 - wrapped for callers
        if isinstance(error, UsUniverseError):
            raise
        LOGGER.warning("us_universe source=nasdaq_symbol_directory failed: %s", error)
        raise UsUniverseError(f"US symbol directory failed: {error}") from error

    entries = dict(nasdaq_entries)
    for ticker, item in other_entries.items():
        existing = entries.get(ticker)
        if existing and (
            existing["exchange"] != item["exchange"]
            or existing["instrument_type"] != item["instrument_type"]
        ):
            raise UsUniverseError(
                f"conflicting authoritative symbol-directory rows for {ticker}"
            )
        entries[ticker] = item

    sources = ["nasdaq_trader_nasdaqlisted", "nasdaq_trader_otherlisted"]
    enriched = 0
    try:
        sec_rows = _sec_enrichment(
            _fetch_bytes(sec_url, opener=open_url, accept="application/json")
        )
    except Exception as error:  # SEC is enrichment, not the breadth authority.
        LOGGER.warning("us_universe source=sec_tickers enrichment failed: %s", error)
        sec_rows = {}
    else:
        sources.append("sec_company_tickers_exchange")
    for ticker, item in entries.items():
        sec = sec_rows.get(ticker)
        if sec:
            item["cik"] = sec["cik"]
            enriched += 1

    stocks = sum(item["instrument_type"] == "stock" for item in entries.values())
    etfs = sum(item["instrument_type"] == "etf" for item in entries.values())
    payload_out = {
        "updated_at": refreshed_at or datetime.now(timezone.utc).isoformat(),
        "source": sources,
        "source_urls": {
            "nasdaq_listed": nasdaq_source_url,
            "other_listed": other_source_url,
            "sec_enrichment": sec_url,
        },
        "source_tier": "official",
        "coverage_boundary": "exchange_listed_only_otc_not_proven",
        "counts": {
            "companies": len(entries),
            "total": len(entries),
            "stocks": stocks,
            "etfs": etfs,
            "sec_cik_enriched": enriched,
        },
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
    """Return normalized ticker identity fields from the cached universe."""
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
            "exchange": str(item.get("exchange") or ""),
            "cik": str(item.get("cik") or ""),
            "instrument_type": str(item.get("instrument_type") or "stock"),
            "universe_source": str(item.get("universe_source") or ""),
        }
    return result


def search_us_universe(
    query: str,
    path: Optional[Path] = None,
) -> List[Mapping[str, Any]]:
    """Search the cached US universe by ticker, name, exchange, type or CIK."""
    payload = load_us_universe(path)
    if not payload:
        return []
    needle = str(query or "").strip().lower()
    if not needle:
        return []
    matches: List[Mapping[str, Any]] = []
    for item in payload.get("items") or []:
        haystack = " ".join(
            str(item.get(key) or "")
            for key in (
                "ticker", "name", "exchange", "cik", "instrument_type",
                "universe_source",
            )
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
