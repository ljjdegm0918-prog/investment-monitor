"""Request-time symbol rules shared by KR news connectors."""

from __future__ import annotations

from .common import normalize_kr_ticker


def kr_yahoo_symbol(ticker: str) -> str:
    """Request-time Yahoo-style symbol for a canonical KR ticker."""
    code = normalize_kr_ticker(ticker)
    return f"{code}.KS"
