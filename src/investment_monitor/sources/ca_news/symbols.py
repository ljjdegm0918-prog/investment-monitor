"""Request-time symbol rules shared by CA news connectors."""

from __future__ import annotations

from ...ca_universe import ca_universe_name_map


def ca_yahoo_symbol(ticker: str) -> str:
    """Request-time Yahoo-style symbol for a canonical CA ticker.

    Uses the CA universe board when cached (TSXV -> ``.V``), otherwise the
    TSX-style ``.TO`` suffix is the default. The stored ticker is never
    suffixed; this is only for the outgoing request.
    """
    code = str(ticker).strip().upper()
    exchange = str(
        (ca_universe_name_map().get(code) or {}).get("exchange") or ""
    )
    suffix = ".V" if exchange == "TSXV" else ".TO"
    return f"{code}{suffix}"
