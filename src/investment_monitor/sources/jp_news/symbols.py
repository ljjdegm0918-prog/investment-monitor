"""Request-time symbol rules shared by JP news connectors."""

from __future__ import annotations

import re


def normalize_jp_ticker(ticker: str) -> str:
    """Normalize a JP ticker without the ``.T`` suffix.

    TSE introduced alphanumeric security codes such as ``473A``; preserving
    the trailing letter is required for ETF directory and news matching.
    """
    code = str(ticker).strip().upper()
    if code.endswith(".T"):
        code = code[:-2]
    compact = re.sub(r"[^0-9A-Z]", "", code)
    if re.fullmatch(r"\d{3}[A-Z]", compact):
        return compact
    digits = re.sub(r"[^0-9]", "", code)
    if digits:
        return digits.zfill(4)
    return code


def jp_yahoo_symbol(ticker: str) -> str:
    """Request-time Yahoo-style symbol for a canonical JP ticker."""
    return f"{normalize_jp_ticker(ticker)}.T"
