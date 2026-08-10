"""Request-time symbol rules shared by PL news connectors."""

from __future__ import annotations


def pl_yahoo_symbol(ticker: str) -> str:
    """Request-time Yahoo-style symbol for a canonical PL ticker.

    GPW/Warsaw symbols use the ``.WA`` suffix at request time (live
    verified 2026-08-10 with ``s=PKO.WA&region=PL``); the stored ticker is
    never suffixed (connectors pass the normalized root).
    """
    code = str(ticker).strip().upper()
    return f"{code}.WA"
