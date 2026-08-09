"""CNMV relevant-information disclosures connector for market=es companies.

Collects Spanish issuers' disclosures from the two key-free official CNMV
RSS feeds (``informacion-privilegiada`` and ``Otra-Informacion-Relevante``).
The feeds are keyed by company name (``Title``), not ticker, so a record is
emitted only when its company name or ISIN matches the ES universe cache
identity for a requested ticker. Requested ES tickers without a universe
identity are skipped and recorded in ``last_errors`` (never a fake success);
the ticker mnemonic is never used as a name pattern. Dates use
Europe/Madrid day bounds.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import List, Mapping, Optional, Sequence, Tuple

from ...models import CollectionRequest, InformationItem, MARKET_ES
from ...universe.es_universe import es_universe_name_map
from ...web_repository import normalize_es_ticker
from .client import (
    CnmvHrClient,
    CnmvHrRequestError,
)
from .matcher import CnmvHrCompanyMatcher

LOGGER = logging.getLogger(__name__)

MAX_LOOKBACK_DAYS = 30


class CnmvHrConnector:
    """Collect CNMV relevant-information disclosures for market=es."""

    name = "cnmv_hr"
    provider = "CNMV (hechos relevantes)"
    max_lookback_days = MAX_LOOKBACK_DAYS

    def __init__(
        self,
        client: Optional[CnmvHrClient] = None,
        universe: Optional[Mapping[str, Mapping[str, str]]] = None,
    ) -> None:
        self._client = client or CnmvHrClient.from_environment()
        self._universe = (
            dict(universe)
            if universe is not None
            else es_universe_name_map()
        )
        self._last_errors: Tuple[Tuple[str, str], ...] = ()

    @property
    def last_errors(self) -> Tuple[Tuple[str, str], ...]:
        return self._last_errors

    def collect(self, request: CollectionRequest) -> List[InformationItem]:
        failures: List[Tuple[str, str]] = []
        es_tickers = tuple(
            normalize_es_ticker(ticker)
            for ticker in request.tickers
            if request.market_for(ticker) == MARKET_ES
        )
        identities: List[Tuple[str, Mapping[str, str]]] = []
        for ticker in es_tickers:
            identity = self._identity_for(ticker)
            if identity is None:
                failures.append((ticker, "no_universe_identity"))
                continue
            identities.append((ticker, identity))
        if not identities:
            # No ES ticker has a universe identity: nothing can be matched
            # and no HTTP request is made (non-es requests stay at zero).
            self._last_errors = tuple(failures)
            return []

        collected_at = datetime.now(timezone.utc)
        try:
            records = self._client.fetch_disclosures(
                request.start_date,
                request.end_date,
            )
        except Exception as error:
            message = str(error) or error.__class__.__name__
            failures.extend((ticker, message) for ticker, _ in identities)
            LOGGER.warning("cnmv_hr status=failure error=%s", message)
            self._last_errors = tuple(failures)
            if len(request.tickers) == 1:
                raise CnmvHrRequestError(message) from error
            return []

        matcher = CnmvHrCompanyMatcher()
        items: List[InformationItem] = []
        for ticker, identity in identities:
            matched = [
                record
                for record in records
                if matcher.matches(
                    record,
                    name=identity.get("name") or "",
                    isin=identity.get("isin") or "",
                )
            ]
            items.extend(
                _map_records(
                    matched,
                    ticker=ticker,
                    collected_at=collected_at,
                )
            )
        self._last_errors = tuple(failures)
        return items

    def _identity_for(
        self, ticker: str
    ) -> Optional[Mapping[str, str]]:
        identity = self._universe.get(ticker)
        if not identity:
            return None
        name = str(identity.get("name") or "").strip()
        isin = str(identity.get("isin") or "").strip().upper()
        if not name and not isin:
            return None
        return {"name": name, "isin": isin}


def _map_records(
    records: Sequence[Mapping[str, object]],
    *,
    ticker: str,
    collected_at: datetime,
) -> List[InformationItem]:
    items: List[InformationItem] = []
    for record in records:
        company_name = str(record.get("company_name") or ticker)
        category = str(record.get("category") or "").strip()
        text = str(record.get("text") or "").strip()
        title = (
            f"{company_name} \u2014 {category}"
            if category
            else company_name
        )
        document_id = str(record.get("nreg") or record["external_id"])
        local_time = record.get("effective")
        items.append(
            InformationItem(
                source="cnmv_hr",
                source_type="regulatory_filing",
                external_id=document_id,
                tickers=(ticker,),
                issuer=company_name,
                published_at=record["published"],
                title=title,
                document_type=category or "hecho_relevante",
                url=str(record["url"]),
                collected_at=collected_at,
                raw_metadata={
                    "provider": "cnmv_rss",
                    "stock_code": ticker,
                    "document_id": document_id,
                    "category": category,
                    "company_name": company_name,
                    "local_time": (
                        local_time.isoformat() if local_time else ""
                    ),
                },
                market=MARKET_ES,
                summary=text or None,
                effective_at=(
                    local_time if isinstance(local_time, datetime)
                    else record["published"]
                ),
            )
        )
    return items
