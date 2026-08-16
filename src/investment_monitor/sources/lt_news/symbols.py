"""Request-time symbol rules shared by LT news connectors."""

from __future__ import annotations


def lt_yahoo_symbol(ticker: str) -> str:
    """Request-time Yahoo-style symbol for a canonical LT ticker.

    NASDAQ BALTIC/Tallinn symbols use the ``.VL`` suffix at request time (live
    verified 2026-08-10 with ``s=PKO.VL&region=LT``); the stored ticker is
    never suffixed (connectors pass the normalized root).
    """
    code = str(ticker).strip().upper()
    return f"{code}.VL"
