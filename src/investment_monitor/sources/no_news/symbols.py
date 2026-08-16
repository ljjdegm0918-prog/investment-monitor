"""Request-time symbol rules shared by NO news connectors."""

from __future__ import annotations


def no_yahoo_symbol(ticker: str) -> str:
    """Request-time Yahoo-style symbol for a canonical NO ticker.

    EURONEXT/Tallinn symbols use the ``.OL`` suffix at request time (live
    verified 2026-08-10 with ``s=PKO.OL&region=NO``); the stored ticker is
    never suffixed (connectors pass the normalized root).
    """
    code = str(ticker).strip().upper()
    return f"{code}.OL"
