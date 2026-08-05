"""Resolve KR tickers to OpenDART corp codes for web list management."""

from __future__ import annotations

from pathlib import Path
from typing import Mapping, Optional

from .client import DartClient
from .corp_code_cache import CorpCodeCache


class DARTCompanyResolver:
    """Map KR stock codes to OpenDART company identities."""

    def __init__(self, cache: CorpCodeCache) -> None:
        self._cache = cache

    @classmethod
    def from_environment(cls, cache_path: Path) -> "DARTCompanyResolver":
        """Build a live resolver from environment configuration."""
        client = DartClient.from_environment()
        return cls(
            CorpCodeCache(
                client=client,
                cache_path=cache_path,
            )
        )

    @classmethod
    def offline(cls, cache_path: Path) -> "DARTCompanyResolver":
        """Build a resolver that only reads an existing local cache."""
        return cls(
            CorpCodeCache(
                client=None,
                cache_path=cache_path,
            )
        )

    def resolve(self, ticker: str) -> Optional[Mapping[str, str]]:
        """Return an OpenDART identity mapping or None when unmapped."""
        try:
            resolved = self._cache.resolve(ticker)
        except Exception:
            return None
        if resolved is None:
            return None
        corp_code, corp_name, normalized_ticker = resolved
        return {
            "ticker": normalized_ticker,
            "name": corp_name,
            "cik": corp_code,
            "exchange": "KRX",
            "mapping_status": "mapped",
        }
