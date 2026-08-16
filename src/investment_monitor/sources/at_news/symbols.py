"""Request-time symbol rules shared by AT news connectors."""

from __future__ import annotations


def at_yahoo_symbol(ticker: str) -> str:
    """Request-time Yahoo-style symbol for a canonical AT ticker.

    WIENER BORSE/Vienna symbols use the ``.VI`` suffix at request time (live
    verified 2026-08-10 with ``s=PKO.VI&region=AT``); the stored ticker is
    never suffixed (connectors pass the normalized root).
    """
    code = str(ticker).strip().upper()
    return f"{code}.VI"
