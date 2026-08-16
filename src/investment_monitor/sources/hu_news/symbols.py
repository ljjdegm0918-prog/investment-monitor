"""Request-time symbol rules shared by HU news connectors."""

from __future__ import annotations


def hu_yahoo_symbol(ticker: str) -> str:
    """Request-time Yahoo-style symbol for a canonical HU ticker.

    BSE (Budapest)/Budapest symbols use the ``.BU`` suffix at request time (live
    verified 2026-08-10 with ``s=PKO.BU&region=HU``); the stored ticker is
    never suffixed (connectors pass the normalized root).
    """
    code = str(ticker).strip().upper()
    return f"{code}.BU"
