"""UK company-number normalization and small seed/cache helper."""

from __future__ import annotations

import json
import logging
import os
import time
from pathlib import Path
from typing import Any, Dict, Optional

LOGGER = logging.getLogger(__name__)

DEFAULT_CACHE_TTL_SECONDS = 24 * 60 * 60

# Verified on 2026-08-06 through the public Companies House web search
# (find-and-update.company-information.service.gov.uk). Runtime profile
# checks still gate mapping, so a stale number degrades to unmapped instead
# of mapping the wrong company.
SEED_COMPANIES: Dict[str, str] = {
    "VOD": "01833679",   # Vodafone Group Public Limited Company
    "BP.": "00102498",   # BP p.l.c.
    "SHEL": "04366849",  # Shell plc
    "HSBA": "00617987",  # HSBC Holdings plc
    "AZN": "02723534",   # AstraZeneca plc
    "GSK": "03888792",   # GSK plc
    "DGE": "00023307",   # Diageo plc
    "BARC": "00048839",  # Barclays PLC
    "ULVR": "00041424",  # Unilever PLC
}


class CompanyNumberCache:
    """Resolve UK tickers to company numbers with a tiny local cache."""

    def __init__(
        self,
        cache_path: Path,
        ttl_seconds: float = DEFAULT_CACHE_TTL_SECONDS,
        clock: Any = time.time,
    ) -> None:
        self._cache_path = Path(cache_path)
        self._ttl_seconds = ttl_seconds
        self._clock = clock
        self._numbers: Optional[Dict[str, str]] = None

    def number_for_ticker(self, ticker: str) -> Optional[str]:
        """Return a company number for a ticker, or None when unknown."""
        raw = ticker.strip().upper()
        if raw.isdigit() and 6 <= len(raw) <= 8:
            return raw.zfill(8)
        seed = SEED_COMPANIES.get(raw)
        if seed is not None:
            return seed
        return self._cached(raw)

    def remember(self, ticker: str, company_number: str) -> None:
        """Persist a verified ticker -> company_number mapping."""
        numbers = self._load()
        numbers[ticker.strip().upper()] = company_number.strip().upper()
        self._cache_path.parent.mkdir(parents=True, exist_ok=True)
        temporary_path = self._cache_path.with_suffix(
            self._cache_path.suffix + ".tmp"
        )
        try:
            with temporary_path.open("w", encoding="utf-8") as cache_file:
                json.dump(numbers, cache_file)
            temporary_path.replace(self._cache_path)
        except OSError as error:
            LOGGER.warning(
                "Could not write Companies House number cache: %s",
                self._cache_path,
            )
            raise

    def _cached(self, ticker: str) -> Optional[str]:
        numbers = self._load()
        number = numbers.get(ticker)
        if number is None:
            return None
        try:
            age = float(self._clock()) - self._cache_path.stat().st_mtime
        except OSError:
            return number
        # A just-written file can report mtime slightly ahead of the clock.
        if -1 <= age <= self._ttl_seconds:
            return number
        return None

    def _load(self) -> Dict[str, str]:
        if self._numbers is not None:
            return self._numbers
        try:
            with self._cache_path.open("r", encoding="utf-8") as cache_file:
                payload = json.load(cache_file)
            self._numbers = {
                str(key): str(value)
                for key, value in payload.items()
            }
        except (OSError, json.JSONDecodeError):
            self._numbers = {}
        return self._numbers
