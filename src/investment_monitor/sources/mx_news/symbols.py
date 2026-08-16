"""Request-time symbol rules shared by MX news connectors."""

from __future__ import annotations


def mx_yahoo_symbol(ticker: str) -> str:
    """Request-time Yahoo-style symbol for a canonical MX ticker.

    BMV/Mexico City symbols use the ``.MX`` suffix at request time (live
    verified 2026-08-10 with ``s=PKO.MX&region=MX``); the stored ticker is
    never suffixed (connectors pass the normalized root).
    """
    code = str(ticker).strip().upper()
    return f"{code}.MX"
