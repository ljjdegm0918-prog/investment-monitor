"""Request-time symbol rules shared by FR news connectors."""

from __future__ import annotations


def fr_yahoo_symbol(ticker: str) -> str:
    """Request-time Yahoo-style symbol for a canonical FR ticker.

    Euronext Paris symbols always use the ``.PA`` suffix at request time;
    the stored ticker is never suffixed (connectors pass the normalized
    root).
    """
    code = str(ticker).strip().upper()
    return f"{code}.PA"
