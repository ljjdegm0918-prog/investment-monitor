# -*- coding: utf-8 -*-
"""IBKR Client Portal secdef search adapter (P0-2, optional real connect).

Contract:

* ``IBKR_SECDEF_BASE_URL`` (e.g. ``https://localhost:5000/v1/api``) and
  ``IBKR_WEB_API_TOKEN`` come from the environment only; neither is ever
  committed or displayed.
* Without a session object AND without both env values configured,
  :func:`search_contracts` performs **no HTTP request** and returns ``[]``
  (honest mock — the Phase 1 rule "no session, no fabricated conid" holds).
* With configuration it uses the documented IBKR Gateway REST shape
  ``GET {base}/iserver/secdef/search?symbol=...`` (plan §2.1) and normalizes
  every record to the Phase 0 field contract:
  ``conid, symbol, localSymbol, secType, currency, primaryExchange,
  validExchanges`` (missing fields stay ``None``/``[]``).

TWS ``reqContractDetails`` is deliberately not implemented here; the
:class:`TwSContractDetailsSession` protocol documents the future gateway
shape only. No new runtime dependency is introduced (stdlib urllib).
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any, Callable, List, Mapping, Optional, Protocol, Tuple
from urllib.parse import urlencode
from urllib.request import Request, urlopen

LOGGER = logging.getLogger(__name__)

DEFAULT_TIMEOUT_SECONDS = 10.0
DEFAULT_USER_AGENT = "InvestmentMonitor/0.1 (internal workspace)"
CONTRACT_FIELDS = (
    "conid",
    "symbol",
    "localSymbol",
    "secType",
    "currency",
    "primaryExchange",
    "validExchanges",
)


class IbkrSecdefError(RuntimeError):
    """Raised when a configured IBKR secdef request fails."""


class TwSContractDetailsSession(Protocol):
    """Future TWS/Gateway session shape (documentation only, not used yet)."""

    def reqContractDetails(self, contract: Mapping[str, Any]) -> Any:  # noqa: N802
        """Request contract details for a TWS contract descriptor."""
        ...


def _configured(
    session: Optional[Any],
    base_url: str,
    api_token: str,
) -> Tuple[bool, str, str]:
    if session is not None:
        resolved_base = (
            getattr(session, "base_url", "")
            or os.environ.get("IBKR_SECDEF_BASE_URL", "")
        ).strip().rstrip("/")
        resolved_token = (
            getattr(session, "api_token", "")
            or os.environ.get("IBKR_WEB_API_TOKEN", "")
        ).strip()
        return bool(resolved_base), resolved_base, resolved_token
    base = (base_url or os.environ.get("IBKR_SECDEF_BASE_URL", "")).strip()
    token = (api_token or os.environ.get("IBKR_WEB_API_TOKEN", "")).strip()
    return bool(base and token), base.rstrip("/"), token


def _fetch_json(
    url: str,
    opener: Callable[..., Any],
    timeout: float,
) -> Any:
    request = Request(
        url,
        headers={
            "User-Agent": DEFAULT_USER_AGENT,
            "Accept": "application/json",
        },
    )
    with opener(request, timeout=timeout) as response:
        raw = response.read()
    return json.loads(raw.decode("utf-8"))


def _normalize_record(record: Mapping[str, Any]) -> Dict[str, Any]:
    conid = record.get("conid") if record.get("conid") is not None else None
    symbol = str(record.get("symbol") or "")
    local_symbol = str(record.get("localSymbol") or symbol)
    sec_type = str(record.get("secType") or record.get("assetType") or "")
    currency = str(record.get("currency") or "")
    primary_exchange = str(
        record.get("primaryExchange") or record.get("listingExchange") or ""
    )
    valid_exchanges = record.get("validExchanges") or []
    if isinstance(valid_exchanges, str):
        valid_exchanges = [valid_exchanges]
    return {
        "conid": str(conid) if conid is not None else None,
        "symbol": symbol or None,
        "localSymbol": local_symbol or None,
        "secType": sec_type or None,
        "currency": currency or None,
        "primaryExchange": primary_exchange or None,
        "validExchanges": [str(item) for item in valid_exchanges],
        "description": str(record.get("description") or ""),
        "companyName": str(record.get("companyName") or ""),
        "source": "ibkr_secdef_search",
    }


def search_contracts(
    symbol: str,
    *,
    exchange: str = "",
    market: str = "",
    session: Optional[Any] = None,
    api_token: str = "",
    base_url: str = "",
    opener: Optional[Callable[..., Any]] = None,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
) -> List[Dict[str, Any]]:
    """Search IBKR secdef for a symbol; ``[]`` when not configured.

    ``exchange`` is the IBKR exchange/venue code when known; ``market`` is
    carried through for callers (it is not sent to the API).
    """
    configured, resolved_base, resolved_token = _configured(
        session, base_url, api_token
    )
    if not configured:
        LOGGER.debug(
            "ibkr secdef skipped: no session and IBKR_SECDEF_BASE_URL/"
            "IBKR_WEB_API_TOKEN are not both set"
        )
        return []
    query = urlencode({"symbol": symbol})
    if exchange:
        query += f"&name={exchange}"  # secdef search alias
    url = f"{resolved_base}/iserver/secdef/search?{query}"
    try:
        payload = _fetch_json(url, opener or urlopen, timeout)
    except Exception as error:  # noqa: BLE001 - 调用方决定降级
        raise IbkrSecdefError(
            f"IBKR secdef search failed for {symbol}: {error}"
        ) from error
    if not isinstance(payload, list):
        raise IbkrSecdefError(
            f"IBKR secdef search returned {type(payload).__name__}, expected list"
        )
    normalized: List[Dict[str, Any]] = []
    for record in payload:
        if not isinstance(record, Mapping):
            continue
        row = _normalize_record(record)
        row["market"] = market
        row["exchange"] = exchange
        normalized.append(row)
    return normalized


def contract_details(
    conid: str,
    *,
    session: Optional[Any] = None,
    api_token: str = "",
    base_url: str = "",
    opener: Optional[Callable[..., Any]] = None,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
) -> Dict[str, Any]:
    """Fetch full contract fields for one conid (secdef/info shape)."""
    configured, resolved_base, _resolved_token = _configured(
        session, base_url, api_token
    )
    if not configured:
        return {}
    url = f"{resolved_base}/iserver/secdef/info?conid={conid}"
    try:
        payload = _fetch_json(url, opener or urlopen, timeout)
    except Exception as error:  # noqa: BLE001
        raise IbkrSecdefError(
            f"IBKR secdef info failed for conid={conid}: {error}"
        ) from error
    if not isinstance(payload, list) or not payload:
        return {}
    first = payload[0]
    return _normalize_record(first if isinstance(first, Mapping) else {})


__all__ = [
    "CONTRACT_FIELDS",
    "IbkrSecdefError",
    "TwSContractDetailsSession",
    "contract_details",
    "search_contracts",
]
