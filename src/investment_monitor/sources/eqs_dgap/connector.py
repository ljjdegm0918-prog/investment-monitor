"""EQS News / DGAP regulatory disclosures for market=de companies.

Collects German issuer disclosures from the key-free EQS News JSON API
(``/wp-json/eqsnews/v1/news?isin=...``). Matching is by ISIN from the DE
universe cache (or a German ISIN typed as the ticker). Requested DE tickers
without an ISIN are skipped and recorded in ``last_errors`` (never a fake
success). Dates use Europe/Berlin day bounds.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import List, Mapping, Optional, Tuple

from ...models import CollectionRequest, InformationItem, MARKET_DE
from ...provenance import build_raw_provenance
from ...universe.de_universe import de_universe_name_map
from ...web_repository import normalize_de_ticker
from .client import EqsDgapClient, EqsDgapRequestError, berlin_day

LOGGER = logging.getLogger(__name__)

MAX_LOOKBACK_DAYS = 30
_ISIN_PREFIX = "DE"


class EqsDgapConnector:
    """Collect EQS/DGAP regulatory disclosures for market=de companies."""

    name = "eqs_dgap"
    provider = "EQS News (DGAP)"
    max_lookback_days = MAX_LOOKBACK_DAYS

    def __init__(
        self,
        client: Optional[EqsDgapClient] = None,
        universe: Optional[Mapping[str, Mapping[str, str]]] = None,
    ) -> None:
        self._client = client or EqsDgapClient.from_environment()
        self._universe = (
            dict(universe) if universe is not None else de_universe_name_map()
        )
        self._last_errors: Tuple[Tuple[str, str], ...] = ()

    @property
    def last_errors(self) -> Tuple[Tuple[str, str], ...]:
        return self._last_errors

    def collect(self, request: CollectionRequest) -> List[InformationItem]:
        failures: List[Tuple[str, str]] = []
        jobs: List[Tuple[str, str]] = []
        for ticker in request.tickers:
            if request.market_for(ticker) != MARKET_DE:
                LOGGER.info(
                    "eqs_dgap ticker=%s market=%s skipped not_de_market",
                    ticker,
                    request.market_for(ticker),
                )
                continue
            code = normalize_de_ticker(ticker)
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
                    "eqs_dgap ticker=%s status=failure error=%s",
                    code,
                    message,
                )
                if len(request.tickers) == 1:
                    self._last_errors = tuple(failures)
                    raise EqsDgapRequestError(message) from error
                continue
            for record in records:
                day = berlin_day(record["published_at"])
                if day < request.start_date or day > request.end_date:
                    continue
                items.append(
                    InformationItem(
                        source="eqs_dgap",
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
                            **build_raw_provenance(
                                official_source_id=str(
                                    record.get("locale_id") or ""
                                ),
                                official_source_url=str(record["url"]),
                                retrieval_url=str(
                                    record.get("retrieval_url") or ""
                                ),
                                raw_payload=record.get("raw_payload") or record,
                                raw_payload_format="json",
                                classification_code=str(
                                    record.get("category_code") or ""
                                ),
                                classification_label=str(
                                    record.get("category") or ""
                                ),
                                published_at_raw=str(
                                    record.get("published_at_raw") or ""
                                ),
                                published_timezone=str(
                                    record.get("published_timezone")
                                    or "unknown"
                                ),
                            ),
                            "provider": "eqs_news",
                            "stock_code": code,
                            "isin": isin,
                            "category": record.get("category"),
                            "category_code": record.get("category_code"),
                            "locale_id": record.get("locale_id"),
                        },
                        market=MARKET_DE,
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
