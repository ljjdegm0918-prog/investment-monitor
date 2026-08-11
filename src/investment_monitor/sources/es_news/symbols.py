"""Request-time symbol rules shared by ES news connectors."""

from __future__ import annotations


def es_yahoo_symbol(ticker: str) -> str:
    """Request-time Yahoo-style symbol for a canonical ES ticker.

    BME / Bolsa de Madrid symbols always use the ``.MC`` suffix at request
    time; the stored ticker is never suffixed (connectors pass the
    normalized root).
    """
    code = str(ticker).strip().upper()
    return f"{code}.MC"
