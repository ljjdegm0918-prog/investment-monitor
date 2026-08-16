# -*- coding: utf-8 -*-
"""IBKR contract reference adapter (P1-6, optional).

Phase 1 treats the IBKR ``conid`` as optional enrichment. This workspace has
no IBKR Gateway / TWS session provisioned, so the adapter is a deterministic
mock: without a session object it returns ``None`` and never invents a
``conid``. When a future deployment provides a session-like object exposing
``lookup_contract(symbol, exchange) -> {"conid": ...}``, the same entry point
starts returning real contract metadata without contract changes elsewhere.
"""

from __future__ import annotations

import logging
from typing import Any, Mapping, Optional, Sequence

LOGGER = logging.getLogger(__name__)


class IbkrReferenceError(RuntimeError):
    """Raised when an explicit IBKR session is configured but unusable."""


def ibkr_conid_for(
    symbol: str,
    market: str,
    session: Optional[Any] = None,
) -> Optional[str]:
    """Return the IBKR ``conid`` for a symbol, or None when unavailable.

    ``session`` may be any object exposing
    ``lookup_contract(symbol, exchange)``. Without it this is an honest
    mock: no network call, no fabricated identifier.
    """
    if session is None:
        return None
    lookup = getattr(session, "lookup_contract", None)
    if not callable(lookup):
        raise IbkrReferenceError(
            "IBKR session object has no callable lookup_contract"
        )
    result = lookup(symbol, market)
    if not isinstance(result, Mapping):
        return None
    conid = result.get("conid")
    return str(conid) if conid is not None else None


def enrich_with_ibkr_conids(
    candidates: Sequence[Mapping[str, Any]],
    session: Optional[Any] = None,
) -> Sequence[Mapping[str, Any]]:
    """Optionally attach ``ibkr_conid`` to candidates (mock no-op without session)."""
    if session is None:
        LOGGER.debug("ibkr reference skipped: no gateway session")
        return candidates
    enriched = []
    for candidate in candidates:
        row = dict(candidate)
        row["ibkr_conid"] = ibkr_conid_for(
            str(row.get("symbol") or ""),
            str(row.get("market") or ""),
            session,
        )
        enriched.append(row)
    return enriched


__all__ = [
    "IbkrReferenceError",
    "enrich_with_ibkr_conids",
    "ibkr_conid_for",
]
