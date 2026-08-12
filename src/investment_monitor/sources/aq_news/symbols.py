"""Request-time symbol rules shared by AQ news connectors."""

from __future__ import annotations


def aq_yahoo_symbol(ticker: str) -> str:
    """Request-time Yahoo-style symbol for a canonical AQSE ticker.

    AQSE instruments use the ``.AQ`` suffix at request time (live verified
    2026-08-10 with ``s=ADB.AQ&region=GB``); the stored ticker is never
    suffixed (connectors pass the normalized root).
    """
    code = str(ticker).strip().upper()
    return f"{code}.AQ"
