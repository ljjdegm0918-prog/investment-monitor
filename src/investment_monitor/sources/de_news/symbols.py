"""Request-time Yahoo symbol helpers for Germany."""

from __future__ import annotations

from ...web_repository import normalize_de_ticker


def de_yahoo_symbol(ticker: str) -> str:
    """Canonical DE root plus ``.DE`` for Yahoo/Google request time only."""
    code = normalize_de_ticker(ticker)
    return f"{code}.DE"
