"""SG tradeable universe cache from the public StocksSG company directory.

SG-2 spike (2026-08-10) found no stable key-free official directory for
SGX equities:

* SGX listed-company pages (``www.sgx.com/securities/*``) are a JS SPA; the
  stock screener is powered by Refinitiv/LSEG and has no documented public
  JSON/CSV export.
* ``api.sgx.com`` routes return 403 (undocumented AWS Gateway; no stable
  free list endpoint; SGX DataLink is a paid market-data product and is not
  used).
* ``data.gov.sg`` holds only aggregate SINGSTAT turnover for SGX boards,
  not a securities directory; the ACRA registry is the full company
  register (no SGX ticker/board/ISIN).
* A hand-written STI list would be exactly the forbidden "STI seed
  pretending to be the full universe", so none is shipped.

StocksSG is a Singapore-focused third party, not SGX.  Its public directory
currently exposes ticker, company name, UEN, board, ISIN and LEI.  The result
is useful reference data but is explicitly partial and must not be presented
as an official or complete SGX security master.  The cache is breadth only
and never flows into information_items.
"""

from __future__ import annotations

import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, List, Mapping, Optional
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

DEFAULT_CACHE_PATH = ".cache/investment_monitor/sg_universe.json"
DIRECTORY_URL = "https://stocks.com.sg/api/v1/companies"

# Phase 4 锁边（2026-08-16 live 复验）：api.sgx.com/securities 返回行情
# prices 结构而非证券目录（params 未公开）；announcements 403；网页仍 SPA。
PHASE4_BOUNDARY = {
    "universe": "partial",
    "disclosure": "unavailable",
    "evidence": (
        "StocksSG public company directory (third-party, incomplete); "
        "official api.sgx.com announcements remains 403 / website SPA"
    ),
}


class SgUniverseError(RuntimeError):
    """Raised when the SG universe cannot be refreshed at all."""


def load_sg_universe(
    path: Optional[Path] = None,
) -> Optional[Mapping[str, Any]]:
    """Load a cached SG universe payload, or None when absent/invalid."""
    cache_path = _cache_path(path)
    try:
        with cache_path.open("r", encoding="utf-8") as cache_file:
            return json.load(cache_file)
    except (OSError, json.JSONDecodeError):
        return None


def refresh_sg_universe(
    *,
    path: Optional[Path] = None,
    opener=None,
    refreshed_at: Optional[str] = None,
) -> Mapping[str, Any]:
    """Refresh the partial third-party SG directory with strict validation."""
    fetch = opener or urlopen
    request = Request(
        DIRECTORY_URL,
        headers={
            "User-Agent": "Mozilla/5.0 (compatible; InvestmentMonitor/0.1)",
            "Accept": "application/json",
        },
    )
    try:
        with fetch(request, timeout=30) as response:
            decoded = json.loads(response.read().decode("utf-8"))
    except (HTTPError, URLError, OSError, json.JSONDecodeError) as error:
        raise SgUniverseError(f"StocksSG directory request failed: {error}") from error
    if not isinstance(decoded, Mapping) or not isinstance(decoded.get("data"), list):
        raise SgUniverseError("StocksSG directory response shape changed")
    raw_rows = decoded["data"]
    meta = decoded.get("meta")
    try:
        reported_count = int(meta.get("count")) if isinstance(meta, Mapping) else -1
    except (TypeError, ValueError):
        reported_count = -1
    if reported_count != len(raw_rows):
        raise SgUniverseError("StocksSG directory count mismatch")
    if len(raw_rows) < 100:
        raise SgUniverseError("StocksSG directory is unexpectedly small")
    items = []
    seen: set[str] = set()
    for row in raw_rows:
        if not isinstance(row, Mapping):
            raise SgUniverseError("StocksSG company row is not an object")
        ticker = str(row.get("ticker") or "").strip().upper()
        name = str(row.get("company_name") or "").strip()
        if ticker.startswith("^"):
            continue
        if not re.fullmatch(r"[A-Z0-9]{1,8}", ticker) or not name:
            raise SgUniverseError("StocksSG company row has invalid ticker or name")
        if row.get("is_active") is False:
            continue
        if ticker in seen:
            raise SgUniverseError(f"StocksSG duplicate ticker: {ticker}")
        seen.add(ticker)
        board = str(row.get("board") or "SGX").strip()
        isin = _optional_identifier(row.get("isin"), r"[A-Z]{2}[A-Z0-9]{9}[0-9]", "ISIN")
        uen = _optional_identifier(row.get("uen"), r"[A-Z0-9-]{8,20}", "UEN")
        lei = _optional_identifier(row.get("lei"), r"[A-Z0-9]{20}", "LEI")
        items.append({
            "ticker": ticker,
            "name": name,
            "board": board,
            "exchange": board,
            "isin": isin,
            "uen": uen,
            "lei": lei,
            "source_tier": "third_party",
        })
    if len(items) < 100:
        raise SgUniverseError("StocksSG usable company directory is unexpectedly small")
    counts: dict[str, int] = {}
    for item in items:
        counts[item["board"]] = counts.get(item["board"], 0) + 1
    payload = {
        "updated_at": refreshed_at or datetime.now(timezone.utc).isoformat(),
        "source": ["stockssg_public_companies"],
        "source_url": DIRECTORY_URL,
        "source_tier": "third_party",
        "coverage": "partial_not_official_sgx_master",
        "counts": counts,
        "items": items,
    }
    cache_path = _cache_path(path)
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = cache_path.with_suffix(cache_path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    temporary.replace(cache_path)
    return payload


def sg_universe_name_map(
    path: Optional[Path] = None,
) -> Mapping[str, Mapping[str, str]]:
    """Return normalized ticker -> {name, exchange, board, isin}."""
    payload = load_sg_universe(path)
    if not payload:
        return {}
    result: dict = {}
    for item in payload.get("items") or []:
        ticker = str(item.get("ticker") or "").strip()
        if not ticker:
            continue
        board = str(
            item.get("board")
            or item.get("exchange")
            or "SGX Mainboard"
        )
        result[ticker] = {
            "name": str(item.get("name") or ticker),
            "exchange": board,
            "board": board,
            "isin": str(item.get("isin") or ""),
        }
    return result


def search_sg_universe(
    query: str,
    path: Optional[Path] = None,
) -> List[Mapping[str, Any]]:
    """Search the cached SG universe by ticker, name, ISIN or board."""
    payload = load_sg_universe(path)
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


def _cache_path(path: Optional[Path]) -> Path:
    return Path(
        path or os.environ.get("SG_UNIVERSE_CACHE_PATH", DEFAULT_CACHE_PATH)
    )


def _optional_identifier(raw: Any, pattern: str, label: str) -> str:
    value = str(raw or "").strip().upper()
    if value and re.fullmatch(pattern, value) is None:
        raise SgUniverseError(f"StocksSG company row has invalid {label}")
    return value
