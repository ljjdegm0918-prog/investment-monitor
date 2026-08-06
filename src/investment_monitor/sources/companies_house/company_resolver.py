"""Resolve UK tickers to Companies House numbers for web list management.

Trust model: only ``mapped`` numbers are verified and collectible.
- Verified automatically: SEED_COMPANIES hits, explicit 6-8 digit company
  number input, or a user Confirm (all gated by a successful profile).
- A unique active name search produces a **candidate** only:
  ``mapping_status=unverified``, honest exchange label, and no trusted-cache
  write. Unique search is NOT proof of the listed issuer.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any, Mapping, Optional

from .client import (
    CompaniesHouseClient,
    CompaniesHouseRequestError,
)
from .company_cache import SEED_COMPANIES, CompanyNumberCache

LOGGER = logging.getLogger(__name__)

DEFAULT_SCRUB_SENTINEL = ".cache/investment_monitor/ch_mapping_legacy_scrubbed"


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
                candidate = self._search_unique(raw)
                if candidate is None:
                    return None
                profile = self._client.get_company(candidate)
                return {
                    "ticker": raw,
                    "name": str(
                        profile.get("company_name") or raw
                    ),
                    "cik": candidate,
                    "exchange": "Unverified",
                    "mapping_status": "unverified",
                }
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

    def confirm(
        self,
        ticker: str,
        company_number: Optional[str] = None,
    ) -> Optional[Mapping[str, str]]:
        """Verify a candidate mapping via profile check and trust it."""
        if self._client is None:
            return None
        raw = ticker.strip().upper()
        number = (company_number or "").strip() or (
            self._cache.number_for_ticker(raw) or ""
        )
        if not number:
            return None
        try:
            profile = self._client.get_company(number)
            self._cache.remember(raw, number)
        except CompaniesHouseRequestError as error:
            if error.status_code == 404:
                return None
            LOGGER.warning(
                "Companies House confirm failed for %s: %s",
                raw,
                error,
            )
            return None
        except Exception:
            return None
        return {
            "ticker": raw,
            "name": str(profile.get("company_name") or raw),
            "cik": number,
            "exchange": "LSE",
            "mapping_status": "mapped",
        }

    def revalidate_legacy(
        self,
        repository: Any,
        sentinel_path: Optional[Path] = None,
    ) -> int:
        """Clean legacy unique-search mappings once, then protect Confirm.

        First run (no sentinel file): every non-seed / non-explicit-number
        UK row with a cik is force-downgraded to ``unverified`` and removed
        from the trusted cache (this scrubs the historical "unique search =
        mapped" mistake), then the sentinel is written.

        Later runs (sentinel exists) use steady-state rules:
        1. seed match or explicit company-number ticker -> ``mapped``
        2. ``mapped`` with a non-empty cik -> keep ``mapped`` and refill the
           trusted cache (user-confirmed mappings survive restarts and
           quiet periods; cache is a persistent store, not a TTL view)
        3. ``unverified`` -> stay ``unverified`` (idempotent forget)
           (legacy dirty unique-search mappings were already scrubbed once
           by the first run)

        Existing companies and stored filings are never deleted.
        """
        sentinel = Path(
            sentinel_path
            or os.environ.get(
                "CH_MAPPING_LEGACY_SCRUB_SENTINEL",
                DEFAULT_SCRUB_SENTINEL,
            )
        )
        first_run = not sentinel.exists()
        changed = 0
        for company in repository.companies():
            if (
                str(company.get("market") or "") != "uk"
                or not company.get("cik")
            ):
                continue
            ticker = str(company.get("ticker") or "").strip()
            cik = str(company.get("cik") or "").strip()
            seed_number = SEED_COMPANIES.get(ticker)
            if seed_number is not None and cik == seed_number:
                status = "mapped"
            elif (
                ticker.isdigit()
                and 6 <= len(ticker) <= 8
                and cik == ticker.zfill(8)
            ):
                status = "mapped"
            elif first_run:
                status = "unverified"
            else:
                current = str(company.get("mapping_status") or "")
                if current == "unverified":
                    status = "unverified"
                elif current == "mapped" and cik:
                    status = "mapped"
                else:
                    status = "unverified"
            if status == "mapped":
                self._cache.remember(ticker, cik)
            else:
                self._cache.forget(ticker)
            if status != str(company.get("mapping_status") or ""):
                repository.set_company_mapping_status(
                    ticker,
                    "uk",
                    status,
                )
                changed += 1
        if first_run:
            sentinel.parent.mkdir(parents=True, exist_ok=True)
            sentinel.write_text(
                "legacy CH mapping scrub completed\n",
                encoding="utf-8",
            )
        return changed

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
