"""Request-time symbol rules shared by SE news connectors."""

from __future__ import annotations


def se_yahoo_symbol(ticker: str) -> str:
    """Request-time Yahoo-style symbol for a canonical SE ticker.

    Nasdaq Stockholm symbols use the ``.ST`` suffix at request time (live
    verified 2026-08-10 with ``s=ERIC-B.ST&region=SE``); the stored ticker is
    never suffixed (connectors pass the normalized root).
    """
    code = str(ticker).strip().upper()
    return f"{code}.ST"
