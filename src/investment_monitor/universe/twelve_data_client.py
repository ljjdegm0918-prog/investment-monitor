# -*- coding: utf-8 -*-
"""Twelve Data optional enrichment client (P1-3).

The Phase 1 pipeline treats Twelve Data as optional: the stage is skipped
unless ``TWELVE_DATA_API_KEY`` is present (the orchestration layer records
``skipped_twelve_no_key``). Probing on 2026-08-15 showed that the key-free
``/symbol_search`` endpoint currently returns 200 for small queries, but
that behaviour is not contractual; ``allow_no_key=True`` is the explicit
opt-in for controlled use.

Enrichment is provenance-only (``twelve_*`` prefixed fields); it never
overwrites official or EODHD display fields.
"""

from __future__ import annotations

import json
import logging
import os
import time
from typing import Any, Callable, Dict, List, Mapping, Optional
from urllib.parse import urlencode
from urllib.request import Request, urlopen

LOGGER = logging.getLogger(__name__)

DEFAULT_BASE_URL = "https://api.twelvedata.com"
DEFAULT_TIMEOUT_SECONDS = 15.0
DEFAULT_MAX_SYMBOLS = 25
DEFAULT_PAUSE_SECONDS = 0.3
DEFAULT_USER_AGENT = "InvestmentMonitor/0.1 (internal workspace)"


class TwelveDataClientError(RuntimeError):
    """Raised when a Twelve Data request fails after being attempted."""


def _default_opener() -> Callable[..., Any]:
    return urlopen


def _fetch_json(
    url: str,
    opener: Callable[..., Any],
    timeout: float,
) -> Mapping[str, Any]:
    request = Request(url, headers={"User-Agent": DEFAULT_USER_AGENT})
    with opener(request, timeout=timeout) as response:
        raw = response.read()
    payload = json.loads(raw.decode("utf-8"))
    if not isinstance(payload, Mapping):
        raise TwelveDataClientError(
            f"Twelve Data returned {type(payload).__name__}, expected object"
        )
    return payload


def enrich_with_twelve_quotes(
    candidates: List[Mapping[str, Any]],
    *,
    api_token: str = "",
    allow_no_key: bool = False,
    base_url: str = DEFAULT_BASE_URL,
    opener: Optional[Callable[..., Any]] = None,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
    max_symbols: int = DEFAULT_MAX_SYMBOLS,
    pause_seconds: float = DEFAULT_PAUSE_SECONDS,
) -> List[Dict[str, Any]]:
    """Add ``twelve_*`` provenance fields for symbols that lack an ISIN.

    Returns the candidate list unchanged when no token is configured and
    keyless use was not explicitly allowed.
    """
    enriched = [dict(candidate) for candidate in candidates]
    token = (api_token or os.environ.get("TWELVE_DATA_API_KEY") or "").strip()
    if not token and not allow_no_key:
        return enriched

    target_rows: List[Dict[str, Any]] = []
    for row in enriched:
        if str(row.get("isin") or ""):
            continue
        if row.get("twelve_data_mic_code"):
            continue
        symbol = str(row.get("symbol") or "").strip()
        if not symbol:
            continue
        target_rows.append(row)
        if len(target_rows) >= max_symbols:
            break
    if not target_rows:
        return enriched

    default_opener = opener or _default_opener()
    for row in target_rows:
        symbol = str(row.get("symbol") or "").strip()
        query = urlencode({"symbol": symbol, "outputsize": 30})
        if token:
            query = f"{query}&apikey={token}"
        url = f"{base_url.rstrip('/')}/symbol_search?{query}"
        try:
            payload = _fetch_json(url, default_opener, timeout)
        except Exception as error:  # noqa: BLE001 - 富化失败不致命
            LOGGER.warning(
                "twelve_data symbol_search=%s failed: %s", symbol, error
            )
            continue
        data = payload.get("data")
        if not isinstance(data, list) or not data:
            continue
        matches = [entry for entry in data if isinstance(entry, Mapping)]
        if not matches:
            continue
        row["twelve_data_instrument_name"] = str(
            matches[0].get("instrument_name") or ""
        )
        row["twelve_data_exchange"] = str(matches[0].get("exchange") or "")
        row["twelve_data_mic_code"] = str(matches[0].get("mic_code") or "")
        row["twelve_data_instrument_type"] = str(
            matches[0].get("instrument_type") or ""
        )
        row["twelve_data_country"] = str(matches[0].get("country") or "")
        if pause_seconds:
            time.sleep(pause_seconds)
    return enriched


__all__ = ["TwelveDataClientError", "enrich_with_twelve_quotes"]
