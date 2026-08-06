"""Companies House filing-history connector for market=uk companies."""

from __future__ import annotations

import logging
import os
from datetime import date, datetime, time, timezone
from pathlib import Path
from typing import Any, List, Mapping, Optional, Tuple

from ...connectors.base import ConnectorUnavailableError, SecretField
from ...models import CollectionRequest, InformationItem, MARKET_UK
from .client import (
    CompaniesHouseClient,
    CompaniesHouseRequestError,
    redact_secrets,
)
from .company_cache import CompanyNumberCache

LOGGER = logging.getLogger(__name__)

MAX_LOOKBACK_DAYS = 30


class CompaniesHouseConnector:
    """Collect Companies House filing history for active UK companies.

    Companies House filings are statutory company filings (accounts,
    confirmation statements, officers, charges), not RNS regulatory news.
    The number cache only holds verified mappings, so unverified candidates
    are skipped here without any filing-history request.
    """

    name = "companies_house"
    provider = "Companies House"
    max_lookback_days = MAX_LOOKBACK_DAYS
    secret_fields = (
        SecretField(
            env="COMPANIES_HOUSE_API_KEY",
            label="Companies House API Key",
            kind="password",
            help=(
                "Free Companies House Public Data API key from "
                "https://developer.company-information.service.gov.uk. "
                "Provides statutory filings, not RNS."
            ),
        ),
    )

    def __init__(
        self,
        client: Optional[CompaniesHouseClient] = None,
        cache: Optional[CompanyNumberCache] = None,
    ) -> None:
        self._client = client or CompaniesHouseClient.from_environment()
        self._cache = cache or CompanyNumberCache(
            cache_path=Path(
                os.environ.get(
                    "COMPANIES_HOUSE_NUMBER_CACHE_PATH",
                    ".cache/investment_monitor/companies_house_numbers.json",
                )
            )
        )
        self._last_errors: Tuple[Tuple[str, str], ...] = ()

    @classmethod
    def configuration_error(cls) -> Optional[str]:
        """Return a reason when the source cannot be enabled."""
        if not os.environ.get("COMPANIES_HOUSE_API_KEY", "").strip():
            return (
                "COMPANIES_HOUSE_API_KEY is not configured; "
                "Companies House is not connected."
            )
        return None

    @classmethod
    def from_environment(cls) -> "CompaniesHouseConnector":
        configuration_error = cls.configuration_error()
        if configuration_error is not None:
            raise ConnectorUnavailableError(configuration_error)
        return cls(client=CompaniesHouseClient.from_environment())

    @property
    def last_errors(self) -> Tuple[Tuple[str, str], ...]:
        return self._last_errors

    def collect(self, request: CollectionRequest) -> List[InformationItem]:
        items: List[InformationItem] = []
        failures: List[Tuple[str, str]] = []
        collected_at = datetime.now(timezone.utc)

        for ticker in request.tickers:
            market = request.market_for(ticker)
            if market != MARKET_UK:
                LOGGER.info(
                    "companies_house ticker=%s market=%s skipped not_uk_market",
                    ticker,
                    market,
                )
                continue
            raw = ticker.strip().upper()
            company_number = self._cache.number_for_ticker(raw)
            if not company_number:
                LOGGER.info(
                    "companies_house ticker=%s skipped no_trusted_company_number",
                    raw,
                )
                continue
            try:
                records = self._client.get_filing_history(company_number)
                items.extend(
                    _map_filings(
                        records,
                        ticker=raw,
                        company_number=company_number,
                        start_date=request.start_date,
                        end_date=request.end_date,
                        collected_at=collected_at,
                    )
                )
            except Exception as error:
                message = redact_secrets(
                    str(error) or error.__class__.__name__
                )
                failures.append((ticker, message))
                LOGGER.warning(
                    "companies_house ticker=%s status=failure error=%s",
                    ticker,
                    message,
                )

        self._last_errors = tuple(failures)
        if len(request.tickers) == 1 and failures:
            raise CompaniesHouseRequestError(failures[0][1])
        return items


def _map_filings(
    records: List[Mapping[str, Any]],
    *,
    ticker: str,
    company_number: str,
    start_date: date,
    end_date: date,
    collected_at: datetime,
) -> List[InformationItem]:
    items: List[InformationItem] = []
    for record in records:
        if not isinstance(record, dict):
            continue
        transaction_id = str(record.get("transaction_id") or "").strip()
        description = str(record.get("description") or "").strip()
        if not transaction_id or not description:
            continue
        filing_date = _parse_filing_date(str(record.get("date") or "").strip())
        if filing_date is None:
            continue
        if not start_date <= filing_date <= end_date:
            continue
        links = record.get("links") or {}
        published_at = datetime.combine(
            filing_date,
            time.min,
            tzinfo=timezone.utc,
        )
        filing_type = str(record.get("type") or "").strip() or "filing"
        items.append(
            InformationItem(
                source="companies_house",
                source_type="regulatory_filing",
                external_id=transaction_id,
                tickers=(ticker,),
                issuer=ticker,
                published_at=published_at,
                title=description,
                document_type=filing_type,
                url=(
                    "https://find-and-update.company-information.service.gov.uk/"
                    f"company/{company_number}/filing-history/{transaction_id}"
                ),
                collected_at=collected_at,
                raw_metadata={
                    "provider": "companies_house",
                    "company_number": company_number,
                    "transaction_id": transaction_id,
                    "type": filing_type,
                    "category": str(record.get("category") or ""),
                    "description": description,
                    "document_metadata_url": str(
                        (links.get("document_metadata_url") or "")
                        if isinstance(links, dict)
                        else ""
                    ),
                },
                market=MARKET_UK,
                summary=None,
                effective_at=published_at,
            )
        )
    return items


def _parse_filing_date(value: str) -> Optional[date]:
    if not value:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None
