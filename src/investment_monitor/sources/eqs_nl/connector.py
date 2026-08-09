"""EQS News (NL) regulatory disclosures for market=nl companies.

Collects Dutch issuer disclosures from the key-free EQS News JSON API
(``/wp-json/eqsnews/v1/news?isin=...``). Matching is by Dutch ISIN (from
the NL universe cache once it exists, or a Dutch ISIN typed as the ticker).
Requested NL tickers without an ISIN are skipped and recorded in
``last_errors`` (never a fake success). EQS coverage of Dutch ISINs is
partial: empty lists are honest. Dates use Europe/Amsterdam day bounds.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import List, Mapping, Optional, Tuple

from ...models import CollectionRequest, InformationItem, MARKET_NL
from ...universe.nl_universe import nl_universe_name_map
from ...web_repository import normalize_nl_ticker
from .client import (
    EqsNlClient,
    EqsNlRequestError,
    amsterdam_day,
)

LOGGER = logging.getLogger(__name__)

MAX_LOOKBACK_DAYS = 30
_ISIN_PREFIX = "NL"


class EqsNlConnector:
    """Collect EQS News disclosures for market=nl companies."""

    name = "eqs_nl"
    provider = "EQS News (NL)"
    max_lookback_days = MAX_LOOKBACK_DAYS

    def __init__(
        self,
        client: Optional[EqsNlClient] = None,
        universe: Optional[Mapping[str, Mapping[str, str]]] = None,
    ) -> None:
        self._client = client or EqsNlClient.from_environment()
        self._universe = (
            dict(universe)
            if universe is not None
            else nl_universe_name_map()
        )
        self._last_errors: Tuple[Tuple[str, str], ...] = ()

    @property
    def last_errors(self) -> Tuple[Tuple[str, str], ...]:
        return self._last_errors

    def collect(self, request: CollectionRequest) -> List[InformationItem]:
        failures: List[Tuple[str, str]] = []
        jobs: List[Tuple[str, str]] = []
        for ticker in request.tickers:
            if request.market_for(ticker) != MARKET_NL:
                LOGGER.info(
                    "eqs_nl ticker=%s market=%s skipped not_nl_market",
                    ticker,
                    request.market_for(ticker),
                )
                continue
            code = normalize_nl_ticker(ticker)
            isin = self._isin_for(code)
            if not isin:
                failures.append((code, "no_universe_isin"))
                continue
            jobs.append((code, isin))
        if not jobs:
            self._last_errors = tuple(failures)
            return []

        collected_at = datetime.now(timezone.utc)
        items: List[InformationItem] = []
        for code, isin in jobs:
            try:
                records = self._client.fetch_by_isin(
                    isin,
                    request.start_date,
                    request.end_date,
                )
            except Exception as error:
                message = str(error) or error.__class__.__name__
                failures.append((code, message))
                LOGGER.warning(
                    "eqs_nl ticker=%s status=failure error=%s",
                    code,
                    message,
                )
                if len(request.tickers) == 1:
                    self._last_errors = tuple(failures)
                    raise EqsNlRequestError(message) from error
                continue
            for record in records:
                day = amsterdam_day(record["published_at"])
                if day < request.start_date or day > request.end_date:
                    continue
                items.append(
                    InformationItem(
                        source="eqs_nl",
                        source_type="regulatory_filing",
                        external_id=str(record["external_id"]),
                        tickers=(code,),
                        issuer=str(
                            record.get("company_name") or code
                        ),
                        published_at=record["published_at"],
                        title=str(record["title"]),
                        document_type=str(
                            record.get("category_code")
                            or record.get("category")
                            or "EQS"
                        ),
                        url=str(record["url"]),
                        collected_at=collected_at,
                        raw_metadata={
                            "provider": "eqs_news",
                            "stock_code": code,
                            "isin": isin,
                            "category": record.get("category"),
                            "category_code": record.get("category_code"),
                            "locale_id": record.get("locale_id"),
                        },
                        market=MARKET_NL,
                        summary=None,
                        effective_at=record["published_at"],
                    )
                )
        self._last_errors = tuple(failures)
        return items

    def _isin_for(self, code: str) -> Optional[str]:
        if code.startswith(_ISIN_PREFIX) and len(code) == 12:
            return code
        identity = self._universe.get(code)
        if not identity:
            return None
        isin = str(identity.get("isin") or "").strip().upper()
        if isin.startswith(_ISIN_PREFIX) and len(isin) == 12:
            return isin
        return None
