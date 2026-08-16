# -*- coding: utf-8 -*-
"""EODHD exchange-symbol-list client for the global equity reference.

P1-2. Uses the key-free *documented* endpoint shape
``https://eodhd.com/api/exchange-symbol-list/{EXCHANGE}?api_token=…&fmt=json``.
The API token is read from ``EODHD_API_KEY``; without a token this module
returns no rows and the orchestration layer records
``skipped_eodhd_no_key`` before any HTTP call is made. The free tier is
budgeted by the caller (default 20 successful calls/day in
``global_equity_reference``) and every attempted HTTP call consumes one
budget unit so a broken token cannot spin the daily loop.
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any, Callable, Dict, List, Mapping, Optional, Tuple
from urllib.parse import urlencode
from urllib.request import Request, urlopen

LOGGER = logging.getLogger(__name__)

DEFAULT_BASE_URL = "https://eodhd.com/api"
DEFAULT_TIMEOUT_SECONDS = 20.0
DEFAULT_USER_AGENT = "InvestmentMonitor/0.1 (internal workspace)"

# 只有权益类进入候选；债券/指数/货币等一律丢弃。
_EQUITY_TYPE_FRAGMENTS = (
    "common stock",
    "preferred",
    "etf",
    "etn",
    "etc",
    "reit",
    "adr",
    "gdr",
    "depositary receipt",
    "unit",
    "right",
    "warrant",
    "fund",
)
_ETF_TYPE_FRAGMENTS = ("etf", "etn", "etc", "fund")


class EodhdClientError(RuntimeError):
    """Raised when every attempted EODHD call failed (no partial data)."""


def _default_opener() -> Callable[..., Any]:
    return urlopen


def _fetch_json(
    url: str,
    opener: Callable[..., Any],
    timeout: float,
) -> Any:
    request = Request(url, headers={"User-Agent": DEFAULT_USER_AGENT})
    with opener(request, timeout=timeout) as response:
        raw = response.read()
    return json.loads(raw.decode("utf-8"))


def _is_equity_type(type_value: Any) -> bool:
    type_text = str(type_value or "").strip().lower()
    if not type_text:
        # 某些交易所列表缺 Type 字段；symbol 列表整体是权益目录，默认收编。
        return True
    return any(fragment in type_text for fragment in _EQUITY_TYPE_FRAGMENTS)


def _instrument_type(type_value: Any) -> str:
    type_text = str(type_value or "").strip().lower()
    if any(fragment in type_text for fragment in _ETF_TYPE_FRAGMENTS):
        return "etf"
    return "stock"


def _candidate_from_row(
    row: Mapping[str, Any],
    market: str,
    exchange: str,
) -> Dict[str, Any]:
    code = str(row.get("Code") or row.get("code") or "").strip()
    name = str(row.get("Name") or row.get("name") or code).strip()
    isin = str(row.get("Isin") or row.get("ISIN") or row.get("isin") or "").strip()
    type_value = row.get("Type") or row.get("type") or ""
    return {
        "market": market,
        "symbol": code,
        "name": name,
        "isin": isin.upper() if isin else "",
        "board": "",
        "instrument_type": _instrument_type(type_value),
        "exchange": str(row.get("Exchange") or exchange),
        "currency": str(row.get("Currency") or row.get("currency") or ""),
        "external_id": f"eodhd:{exchange}:{code}",
        "source": "eodhd:exchange_symbol_list",
        "source_tier": "third_party",
        "verified_at": None,
    }


def collect_eodhd_symbols(
    exchanges: Mapping[str, str],
    budget: Dict[str, Any],
    *,
    api_token: str = "",
    base_url: str = DEFAULT_BASE_URL,
    opener: Optional[Callable[..., Any]] = None,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
) -> Tuple[List[Dict[str, Any]], int]:
    """Fetch one exchange-symbol list per exchange within the daily budget.

    Returns ``(candidates, used_calls)`` where ``used_calls`` counts every
    HTTP attempt made (successful or not). Partial success keeps partial
    rows; if *all* attempts fail, raises :class:`EodhdClientError`.
    """
    token = (api_token or os.environ.get("EODHD_API_KEY") or "").strip()
    if not token:
        return [], 0

    default_opener = opener or _default_opener()
    limit = int(budget.get("limit") or 0)
    used_before = int(budget.get("used_calls") or 0)
    remaining = limit - used_before
    if remaining <= 0:
        return [], 0

    refreshed = set(budget.get("refreshed_exchanges") or [])
    rows: List[Dict[str, Any]] = []
    used = 0
    errors: List[str] = []
    for market in sorted(exchanges):
        exchange = str(exchanges[market] or "").strip()
        if not exchange or exchange in refreshed:
            continue
        if used >= remaining:
            break
        used += 1
        budget["refreshed_exchanges"].append(exchange)
        query = urlencode(
            {"api_token": token, "fmt": "json"}
        )
        url = f"{base_url.rstrip('/')}/exchange-symbol-list/{exchange}?{query}"
        try:
            payload = _fetch_json(url, default_opener, timeout)
            if not isinstance(payload, list):
                raise EodhdClientError(
                    f"EODHD {exchange}: unexpected payload type "
                    f"{type(payload).__name__}"
                )
            for raw_row in payload:
                if not isinstance(raw_row, Mapping):
                    continue
                type_text = str(
                    raw_row.get("Type") or raw_row.get("type") or ""
                )
                if not _is_equity_type(type_text):
                    continue
                code = str(
                    raw_row.get("Code") or raw_row.get("code") or ""
                ).strip()
                if not code:
                    continue
                rows.append(
                    _candidate_from_row(raw_row, market, exchange)
                )
        except Exception as error:  # noqa: BLE001 - 逐交易所收编
            LOGGER.warning(
                "eodhd exchange=%s failed: %s", exchange, error
            )
            errors.append(f"{exchange}:{error}")
    if errors and not rows:
        raise EodhdClientError(
            "EODHD exchange-symbol-list failed for all exchanges: "
            + "; ".join(errors[:3])
        )
    return rows, used


__all__ = ["EodhdClientError", "collect_eodhd_symbols"]
