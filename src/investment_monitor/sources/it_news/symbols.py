"""Request-time symbol rules shared by IT news connectors."""

from __future__ import annotations


def it_yahoo_symbol(ticker: str) -> str:
    """Request-time Yahoo-style symbol for a canonical IT ticker.

    Euronext Milan symbols always use the ``.MI`` suffix at request time;
    the stored ticker is never suffixed (connectors pass the normalized
    root).
    """
    code = str(ticker).strip().upper()
    return f"{code}.MI"
