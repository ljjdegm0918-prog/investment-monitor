"""Request-time symbol rules shared by AU news connectors."""

from __future__ import annotations


def au_yahoo_symbol(ticker: str) -> str:
    """Request-time Yahoo-style symbol for a canonical AU ticker.

    ASX symbols always use the ``.AX`` suffix at request time; the stored
    ticker is never suffixed (connectors pass the normalized root).
    """
    code = str(ticker).strip().upper()
    return f"{code}.AX"
