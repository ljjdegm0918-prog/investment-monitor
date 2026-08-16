# -*- coding: utf-8 -*-
"""Company matcher for Nasdaq Baltic issuer announcements.

The official news API does not return an ISIN or instrument identifier, so
issuer announcements are matched by normalized company name against the
Baltic universe cache (breadth-only directory). Normalization is
conservative: uppercase, whitespace folding and trailing punctuation are
the only transformations; short-code-to-long-name guessing is never done.
When the universe cache is absent or a company name cannot be matched
exactly, the item is skipped honestly instead of being force-attributed.
"""

from __future__ import annotations

import re
from typing import Dict, Iterable, Mapping, Optional, Sequence, Tuple

_WORD_SPACE = re.compile(r"\s+")


def normalize_company_name(name: str) -> str:
    cleaned = str(name or "").strip().upper()
    cleaned = _WORD_SPACE.sub(" ", cleaned)
    while True:
        stripped = cleaned.strip(" .,;:()[]{}")
        if stripped == cleaned:
            return stripped
        cleaned = stripped


class BalticCompanyMatcher:
    """Match Baltic issuer names to canonical tickers via universe cache."""

    def __init__(self) -> None:
        self._names: Dict[str, str] = {}
        self._loaded = False

    def load_universe(self, market: str) -> None:
        from ..universe.nasdaq_baltic_universe import (
            baltic_universe_name_map,
        )

        entries = baltic_universe_name_map(market) or {}
        self._names = {
            ticker: normalize_company_name(str(entry.get("name") or ""))
            for ticker, entry in entries.items()
            if entry.get("name")
        }
        self._loaded = True

    def match(
        self,
        company: str,
        tickers: Sequence[str],
    ) -> Optional[str]:
        """Return the ticker whose universe name exactly matches company."""
        if not self._loaded:
            return None
        target = normalize_company_name(company)
        if not target:
            return None
        for ticker in tickers:
            if self._names.get(ticker) == target:
                return ticker
        return None
