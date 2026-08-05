"""KR tradeable universe cache (breadth only).

This module builds a refreshable list of Korea-listed securities. The
universe is a local cache and never flows into information_items / Filings /
News. Default source is the OpenDART corpCode listing (equity baseline);
data.krx.co.kr is available as an optional key-free adapter, and the KRX Open
API adapter is intentionally disabled (registration requires Korean
identity).
"""

from __future__ import annotations

import json
import logging
import os
from datetime import date, datetime, timedelta, timezone
from http.cookiejar import CookieJar
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional
from urllib.parse import urlencode
from urllib.request import (
    HTTPCookieProcessor,
    HTTPError,
    Request,
    build_opener,
)

from .connectors.base import ConnectorUnavailableError
from .sources.dart.client import DartClient
from .sources.dart.corp_code_cache import CorpCodeCache

LOGGER = logging.getLogger(__name__)

DEFAULT_CACHE_PATH = ".cache/investment_monitor/kr_universe.json"
DATA_KRX_URL = "https://data.krx.co.kr/comm/bldAttendant/getJsonData.cmd"
DATA_KRX_LOADER = (
    "https://data.krx.co.kr/contents/MDC/MDI/mdiLoader/index.cmd"
    "?menuId=MDC0201020101"
)
DATA_KRX_BLD = "dbms/MDC/STAT/standard/MDCSTAT00301"
DATA_KRX_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/126.0 Safari/537.36"
    ),
    "Referer": DATA_KRX_LOADER,
    "Origin": "https://data.krx.co.kr",
    "X-Requested-With": "XMLHttpRequest",
    "Accept": "application/json, text/javascript, */*; q=0.01",
    "Accept-Language": "ko-KR,ko;q=0.9,en;q=0.8",
}
DEFAULT_SOURCE_ORDER = ("dart_corpcode", "data_krx")


class KrUniverseError(RuntimeError):
    """Raised when the KR universe cannot be refreshed."""


def load_kr_universe(
    path: Optional[Path] = None,
) -> Optional[Mapping[str, Any]]:
    """Load the cached universe payload, or None when absent/invalid."""
    cache_path = _cache_path(path)
    try:
        with cache_path.open("r", encoding="utf-8") as cache_file:
            return json.load(cache_file)
    except (OSError, json.JSONDecodeError):
        return None


def refresh_kr_universe(
    *,
    path: Optional[Path] = None,
    source: Optional[str] = None,
    dart_client: Optional[DartClient] = None,
    bas_dt: Optional[str] = None,
) -> Mapping[str, Any]:
    """Refresh the universe cache and return the new payload.

    When ``source`` is omitted, sources are tried in DEFAULT_SOURCE_ORDER so
    a missing key or blocked endpoint degrades instead of hanging the call.
    """
    cache_path = _cache_path(path)
    requested = source or os.environ.get("KR_UNIVERSE_SOURCE", "")
    candidates = (
        (requested,)
        if requested
        else DEFAULT_SOURCE_ORDER
    )
    errors: List[str] = []
    for candidate in candidates:
        try:
            items, source_label = _fetch_source(
                candidate,
                dart_client=dart_client,
                bas_dt=bas_dt,
            )
            payload = {
                "updated_at": datetime.now(timezone.utc).isoformat(),
                "source": source_label,
                "items": items,
            }
            cache_path.parent.mkdir(parents=True, exist_ok=True)
            temporary_path = cache_path.with_suffix(
                cache_path.suffix + ".tmp"
            )
            with temporary_path.open("w", encoding="utf-8") as cache_file:
                json.dump(payload, cache_file, ensure_ascii=False)
            temporary_path.replace(cache_path)
            return payload
        except Exception as error:
            errors.append(f"{candidate}: {error}")
            LOGGER.warning(
                "KR universe source %s failed: %s",
                candidate,
                error,
            )
    raise KrUniverseError("; ".join(errors))


def kr_universe_name_map(
    path: Optional[Path] = None,
) -> Mapping[str, Mapping[str, str]]:
    """Return stock_code -> {name, exchange} for web add-company fallback."""
    payload = load_kr_universe(path)
    if not payload:
        return {}
    result: Dict[str, Mapping[str, str]] = {}
    for item in payload.get("items") or []:
        if not isinstance(item, dict):
            continue
        stock_code = str(item.get("stock_code") or "").strip()
        if not stock_code:
            continue
        result[stock_code] = {
            "name": str(item.get("name") or ""),
            "exchange": str(item.get("exchange") or "KRX"),
        }
    return result


def _fetch_source(
    source: str,
    *,
    dart_client: Optional[DartClient],
    bas_dt: Optional[str],
):
    if source == "dart_corpcode":
        return _source_dart_corpcode(dart_client)
    if source == "data_krx":
        return _source_data_krx(bas_dt)
    if source == "krx_openapi":
        raise KrUniverseError(
            "KRX OpenAPI adapter is disabled: registration requires "
            "Korean identity; use dart_corpcode or data_krx."
        )
    raise KrUniverseError(f"Unknown KR universe source: {source}")


def _source_dart_corpcode(
    dart_client: Optional[DartClient],
) -> tuple:
    client = dart_client or DartClient.from_environment()
    cache = CorpCodeCache(
        client=client,
        cache_path=Path(
            os.environ.get(
                "DART_CORP_CODE_CACHE_PATH",
                ".cache/investment_monitor/dart_corp_codes.json",
            )
        ),
    )
    entries = cache.all_entries()
    items = [
        {
            "stock_code": stock_code,
            "name": corp_name,
            "market_hint": "KRX",
            "instrument_kind": "equity",
            "exchange": "KRX",
        }
        for stock_code, (corp_code, corp_name) in sorted(entries.items())
    ]
    return items, "dart_corpcode"


def _source_data_krx(bas_dt: Optional[str]) -> tuple:
    trade_date = bas_dt or (date.today() - timedelta(days=1)).strftime(
        "%Y%m%d"
    )
    opener = build_opener(HTTPCookieProcessor(CookieJar()))
    try:
        opener.open(
            Request(DATA_KRX_LOADER, headers=DATA_KRX_HEADERS, method="GET"),
            timeout=20,
        )
    except Exception as error:
        raise KrUniverseError(
            f"data.krx.co.kr session could not be established: {error}"
        ) from error
    items: List[Mapping[str, Any]] = []
    for market_id, instrument_kind in (
        ("STK", "equity"),
        ("KSQ", "equity"),
        ("ETF", "etf"),
        ("ETN", "other"),
    ):
        try:
            block = _post_data_krx(opener, trade_date, market_id)
        except Exception as error:
            LOGGER.warning(
                "data_krx market=%s failed: %s",
                market_id,
                error,
            )
            continue
        items.extend(_parse_data_krx_block(block, instrument_kind))
    if not items:
        raise KrUniverseError(
            "data.krx.co.kr returned no universe items "
            "(session may be blocked outside Korea)."
        )
    return items, "data_krx"


def _post_data_krx(opener: Any, trade_date: str, market_id: str) -> List:
    form = {
        "bld": DATA_KRX_BLD,
        "locale": "ko_KR",
        "mktId": market_id,
        "trdDd": trade_date,
        "money": "1",
        "csvxls_isNo": "false",
    }
    request = Request(
        DATA_KRX_URL,
        data=urlencode(form).encode("utf-8"),
        headers=DATA_KRX_HEADERS,
        method="POST",
    )
    try:
        with opener.open(request, timeout=20) as response:
            raw_body = response.read()
    except HTTPError as error:
        detail = error.read().decode("utf-8", errors="replace")[:120]
        raise KrUniverseError(
            f"data.krx.co.kr HTTP {error.code}: {detail}"
        ) from error
    try:
        payload = json.loads(raw_body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise KrUniverseError(
            "data.krx.co.kr returned invalid JSON."
        ) from error
    block = payload.get("OutBlock_1")
    if not isinstance(block, list):
        raise KrUniverseError(
            "data.krx.co.kr response has no OutBlock_1 list."
        )
    return block


def _parse_data_krx_block(
    block: List[Mapping[str, Any]],
    instrument_kind: str,
) -> List[Mapping[str, Any]]:
    items: List[Mapping[str, Any]] = []
    for row in block:
        if not isinstance(row, dict):
            continue
        stock_code = str(row.get("ISU_SRT_CD") or "").strip()
        if not stock_code:
            continue
        items.append(
            {
                "stock_code": stock_code,
                "name": str(row.get("ISU_ABBRV") or ""),
                "market_hint": str(row.get("MKT_NM") or ""),
                "instrument_kind": instrument_kind,
                "exchange": "KRX",
            }
        )
    return items


def _cache_path(path: Optional[Path]) -> Path:
    return Path(
        path
        or os.environ.get("KR_UNIVERSE_CACHE_PATH", DEFAULT_CACHE_PATH)
    )
