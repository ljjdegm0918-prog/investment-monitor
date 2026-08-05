"""Resolve UK tickers to Companies House numbers for web list management."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Mapping, Optional

from .client import (
    CompaniesHouseClient,
    CompaniesHouseRequestError,
)
from .company_cache import CompanyNumberCache

LOGGER = logging.getLogger(__name__)


class CompaniesHouseCompanyResolver:
    """Map UK tickers to verified Companies House identities."""

    def __init__(
        self,
        client: Optional[CompaniesHouseClient],
        cache: CompanyNumberCache,
    ) -> None:
        self._client = client
        self._cache = cache

    @classmethod
    def from_environment(
        cls,
        cache_path: Path,
    ) -> "CompaniesHouseCompanyResolver":
        client = CompaniesHouseClient.from_environment()
        return cls(client, CompanyNumberCache(cache_path))

    @classmethod
    def offline(cls, cache_path: Path) -> "CompaniesHouseCompanyResolver":
        return cls(None, CompanyNumberCache(cache_path))

    def resolve(self, ticker: str) -> Optional[Mapping[str, str]]:
        """Return a Companies House identity mapping or None."""
        if self._client is None:
            return None
        raw = ticker.strip().upper()
        try:
            company_number = self._cache.number_for_ticker(raw)
            if company_number is None:
                company_number = self._search_unique(raw)
            if company_number is None:
                return None
            profile = self._client.get_company(company_number)
            self._cache.remember(raw, company_number)
        except CompaniesHouseRequestError as error:
            if error.status_code == 404:
                return None
            LOGGER.warning(
                "Companies House resolve failed for %s: %s",
                raw,
                error,
            )
            return None
        except Exception:
            return None
        return {
            "ticker": raw,
            "name": str(profile.get("company_name") or raw),
            "cik": company_number,
            "exchange": "LSE",
            "mapping_status": "mapped",
        }

    def _search_unique(self, query: str) -> Optional[str]:
        items = self._client.search_companies(query)
        matches = [
            item
            for item in items
            if isinstance(item, dict)
            and str(item.get("company_status") or "").lower() == "active"
            and item.get("company_number")
        ]
        if len(matches) == 1:
            return str(matches[0]["company_number"])
        return None
