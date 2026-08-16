"""Request-time symbol rules shared by IL news connectors."""

from __future__ import annotations


def il_yahoo_symbol(ticker: str) -> str:
    """Request-time Yahoo-style symbol for a canonical IL ticker.

    TASE/Jerusalem symbols use the ``.TA`` suffix at request time (live
    verified 2026-08-10 with ``s=PKO.TA&region=IL``); the stored ticker is
    never suffixed (connectors pass the normalized root).
    """
    code = str(ticker).strip().upper()
    return f"{code}.TA"
