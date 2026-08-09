"""Request-time symbol rules shared by SG news connectors."""

from __future__ import annotations


def sg_yahoo_symbol(ticker: str) -> str:
    """Request-time Yahoo-style symbol for a canonical SG ticker.

    SGX symbols always use the ``.SI`` suffix at request time; the stored
    ticker is never suffixed (connectors pass the normalized root).
    """
    code = str(ticker).strip().upper()
    return f"{code}.SI"
