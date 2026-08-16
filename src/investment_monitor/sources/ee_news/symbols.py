"""Request-time symbol rules shared by EE news connectors."""

from __future__ import annotations


def ee_yahoo_symbol(ticker: str) -> str:
    """Request-time Yahoo-style symbol for a canonical EE ticker.

    NASDAQ BALTIC/Tallinn symbols use the ``.TL`` suffix at request time (live
    verified 2026-08-10 with ``s=PKO.TL&region=EE``); the stored ticker is
    never suffixed (connectors pass the normalized root).
    """
    code = str(ticker).strip().upper()
    return f"{code}.TL"
