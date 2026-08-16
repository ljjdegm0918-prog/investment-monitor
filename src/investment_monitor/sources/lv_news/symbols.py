"""Request-time symbol rules shared by LV news connectors."""

from __future__ import annotations


def lv_yahoo_symbol(ticker: str) -> str:
    """Request-time Yahoo-style symbol for a canonical LV ticker.

    NASDAQ BALTIC/Tallinn symbols use the ``.RG`` suffix at request time (live
    verified 2026-08-10 with ``s=PKO.RG&region=LV``); the stored ticker is
    never suffixed (connectors pass the normalized root).
    """
    code = str(ticker).strip().upper()
    return f"{code}.RG"
