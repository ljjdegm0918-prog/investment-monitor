"""Request-time symbol rules shared by BE news connectors."""

from __future__ import annotations


def be_yahoo_symbol(ticker: str) -> str:
    """Request-time Yahoo-style symbol for a canonical Belgian ticker.

    Euronext Brussels symbols always use the ``.BR`` suffix at request
    time; the stored ticker is never suffixed (connectors pass the
    normalized root).
    """
    code = str(ticker).strip().upper()
    return f"{code}.BR"
