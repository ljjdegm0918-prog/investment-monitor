"""Request-time symbol rules shared by CH news connectors."""

from __future__ import annotations


def ch_yahoo_symbol(ticker: str) -> str:
    """Request-time Yahoo-style symbol for a canonical CH ticker.

    SIX Swiss Exchange symbols always use the ``.SW`` suffix at request
    time; the stored ticker is never suffixed (connectors pass the
    normalized root).
    """
    code = str(ticker).strip().upper()
    return f"{code}.SW"
