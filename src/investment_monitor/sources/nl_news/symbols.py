"""Request-time symbol rules shared by NL news connectors."""

from __future__ import annotations


def nl_yahoo_symbol(ticker: str) -> str:
    """Request-time Yahoo-style symbol for a canonical NL ticker.

    Euronext Amsterdam symbols always use the ``.AS`` suffix at request
    time; the stored ticker is never suffixed (connectors pass the
    normalized root).
    """
    code = str(ticker).strip().upper()
    return f"{code}.AS"
