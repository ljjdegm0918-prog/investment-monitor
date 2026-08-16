"""Request-time symbol rules shared by IN news connectors."""

from __future__ import annotations


def in_yahoo_symbol(ticker: str) -> str:
    """Request-time Yahoo-style symbol for a canonical IN ticker.

    NSE/Mumbai symbols use the ``.NS`` suffix at request time (live
    verified 2026-08-10 with ``s=PKO.NS&region=IN``); the stored ticker is
    never suffixed (connectors pass the normalized root).
    """
    code = str(ticker).strip().upper()
    return f"{code}.NS"
