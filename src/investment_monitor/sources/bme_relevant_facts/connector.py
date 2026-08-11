"""BME relevant-facts disclosures connector for market=es companies.

Collects Spanish issuers' disclosures from the official key-free BME
relevant-facts JSON API, in parallel with the CNMV RSS connector. Matching
is by the BME ``companyKey`` from the ES universe cache (no ticker-mnemonic
matching). Requested ES tickers without a universe company key are skipped
and recorded in ``last_errors`` (never a fake success). Records are
date-only (``relevantFactDate``), so timestamps use the Europe/Madrid noon
anchor convention and the calendar day drives the requested date window.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import List, Mapping, Optional, Tuple

from ...daily import date_only_market_noon
from ...models import CollectionRequest, InformationItem, MARKET_ES
from ...provenance import build_raw_provenance
from ...universe.es_universe import es_universe_name_map
from ...web_repository import normalize_es_ticker
from .client import (
    BmeRelevantFactsClient,
    BmeRelevantFactsRequestError,
    MADRID,
)

LOGGER = logging.getLogger(__name__)

MAX_LOOKBACK_DAYS = 30


class BmeRelevantFactsConnector:
    """Collect BME relevant facts for market=es companies."""

    name = "bme_relevant_facts"
    provider = "BME Relevant Facts"
    max_lookback_days = MAX_LOOKBACK_DAYS

    def __init__(
        self,
        client: Optional[BmeRelevantFactsClient] = None,
        universe: Optional[Mapping[str, Mapping[str, str]]] = None,
    ) -> None:
        self._client = client or BmeRelevantFactsClient.from_environment()
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
        items: List[InformationItem] = []
        failures: List[Tuple[str, str]] = []
        fetch_failed = False
        collected_at = datetime.now(timezone.utc)
        for ticker in request.tickers:
            market = request.market_for(ticker)
            if market != MARKET_ES:
                LOGGER.info(
                    "bme_relevant_facts ticker=%s market=%s "
                    "skipped not_es_market",
                    ticker,
                    market,
                )
                continue
            code = normalize_es_ticker(ticker)
            company_key = self._company_key_for(code)
            if not company_key:
                failures.append((ticker, "no_universe_company_key"))
                continue
            try:
                records = self._client.fetch_by_company(
                    company_key,
                    request.start_date,
                    request.end_date,
                )
                items.extend(
                    _map_records(
                        records,
                        ticker=code,
                        collected_at=collected_at,
                    )
                )
            except Exception as error:
                fetch_failed = True
                message = str(error) or error.__class__.__name__
                failures.append((ticker, message))
                LOGGER.warning(
                    "bme_relevant_facts ticker=%s status=failure error=%s",
                    ticker,
                    message,
                )
        self._last_errors = tuple(failures)
        if len(request.tickers) == 1 and fetch_failed:
            raise BmeRelevantFactsRequestError(failures[0][1])
        return items

    def _company_key_for(self, ticker: str) -> str:
        identity = self._universe.get(ticker)
        if not identity:
            return ""
        return str(identity.get("company_key") or "").strip()


def _map_records(
    records: List[Mapping[str, object]],
    *,
    ticker: str,
    collected_at: datetime,
) -> List[InformationItem]:
    items: List[InformationItem] = []
    for record in records:
        day = record["day"]
        published = date_only_market_noon(day, MADRID)
        items.append(
            InformationItem(
                source="bme_relevant_facts",
                source_type="regulatory_filing",
                external_id=str(record["external_id"]),
                tickers=(ticker,),
                issuer=str(record.get("issuer_name") or ticker),
                published_at=published,
                title=str(record["title"]),
                document_type=str(record.get("code") or "relevant_fact"),
                url=str(record["url"]),
                collected_at=collected_at,
                raw_metadata={
                    **build_raw_provenance(
                        official_source_id=str(
                            record.get("cnmv_reg_number")
                            or record["external_id"]
                        ),
                        official_source_url=str(record["url"]),
                        retrieval_url=str(
                            record.get("retrieval_url") or ""
                        ),
                        raw_payload=record.get("raw_payload") or record,
                        raw_payload_format="json",
                        classification_code=str(
                            record.get("code") or ""
                        ),
                        classification_label=None,
                        published_at_raw=str(
                            record.get("published_at_raw") or ""
                        ),
                        published_timezone="Europe/Madrid",
                    ),
                    "provider": "bme_relevant_facts_api",
                    "stock_code": ticker,
                    "document_id": str(record["external_id"]),
                    "cnmv_reg_number": str(record.get("cnmv_reg_number") or ""),
                    "nreg": str(record.get("nreg") or ""),
                    "code": str(record.get("code") or ""),
                    "date_only": True,
                    "calendar_date": day.isoformat(),
                    "pdf_url": str(record.get("pdf_url") or ""),
                },
                market=MARKET_ES,
                summary=str(record.get("text") or "") or None,
                effective_at=published,
            )
        )
    return items
