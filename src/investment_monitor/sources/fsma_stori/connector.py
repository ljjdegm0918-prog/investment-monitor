"""FSMA STORI regulatory disclosures connector for market=be companies.

Collects Belgian issuer disclosures from the key-free official FSMA STORI
API (``webapi.fsma.be/api/v1/<lang>/stori/result``) - the FSMA's central
storage of regulated information, the Belgian counterpart of the AMF OAM
feed. Matching is by Belgian ISIN (from the BE universe cache once it
exists, or a Belgian ISIN typed as the ticker) and, as a fallback, by the
universe company name; the ticker mnemonic is never passed to the API and
never used as a name pattern (``ABI`` does not match ``AB INBEV``).
Requested BE tickers without a universe identity are skipped and recorded
in ``last_errors`` (never a fake success). Dates use Europe/Brussels day
bounds and are constrained both server-side and client-side.
"""

from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from typing import Any, List, Mapping, Optional, Tuple

from ...models import CollectionRequest, InformationItem, MARKET_BE
from ...web_repository import normalize_be_ticker
from .client import (
    DEFAULT_PUBLIC_PORTAL,
    StoriClient,
    StoriRequestError,
    brussels_day,
)
from .matcher import StoriCompanyMatcher

LOGGER = logging.getLogger(__name__)

MAX_LOOKBACK_DAYS = 30
_BE_ISIN_RE = re.compile(r"^BE[0-9]{10}$")


class StoriConnector:
    """Collect FSMA STORI disclosures for market=be companies."""

    name = "fsma_stori"
    provider = "FSMA STORI"
    max_lookback_days = MAX_LOOKBACK_DAYS

    def __init__(
        self,
        client: Optional[StoriClient] = None,
        universe: Optional[Mapping[str, Mapping[str, str]]] = None,
    ) -> None:
        self._client = client or StoriClient.from_environment()
        self._universe = (
            dict(universe)
            if universe is not None
            else _default_universe()
        )
        self._last_errors: Tuple[Tuple[str, str], ...] = ()

    @property
    def last_errors(self) -> Tuple[Tuple[str, str], ...]:
        return self._last_errors

    def collect(self, request: CollectionRequest) -> List[InformationItem]:
        failures: List[Tuple[str, str]] = []
        jobs: List[Tuple[str, Mapping[str, str]]] = []
        for ticker in request.tickers:
            if request.market_for(ticker) != MARKET_BE:
                LOGGER.info(
                    "fsma_stori ticker=%s market=%s skipped not_be_market",
                    ticker,
                    request.market_for(ticker),
                )
                continue
            code = normalize_be_ticker(ticker)
            identity = self._identity_for(code)
            if identity is None:
                failures.append((code, "no_universe_identity"))
                continue
            jobs.append((code, identity))
        if not jobs:
            # No BE ticker has a resolvable identity: nothing can be matched
            # and no HTTP request is made (non-be requests stay at zero).
            self._last_errors = tuple(failures)
            return []

        collected_at = datetime.now(timezone.utc)
        items: List[InformationItem] = []
        matcher = StoriCompanyMatcher()
        for code, identity in jobs:
            try:
                if identity["isin"]:
                    records = self._client.fetch_by_isin(
                        identity["isin"],
                        request.start_date,
                        request.end_date,
                    )
                else:
                    records = self._client.fetch_by_company_name(
                        identity["name"],
                        request.start_date,
                        request.end_date,
                    )
            except Exception as error:
                message = str(error) or error.__class__.__name__
                failures.append((code, message))
                LOGGER.warning(
                    "fsma_stori ticker=%s status=failure error=%s",
                    code,
                    message,
                )
                if len(request.tickers) == 1:
                    self._last_errors = tuple(failures)
                    raise StoriRequestError(message) from error
                continue
            for record in records:
                if (
                    brussels_day(record["published"]) < request.start_date
                    or brussels_day(record["published"]) > request.end_date
                ):
                    continue
                if not matcher.matches(
                    record,
                    name=identity["name"],
                    isin=identity["isin"],
                ):
                    continue
                items.append(
                    _map_record(
                        record,
                        ticker=code,
                        identity=identity,
                        collected_at=collected_at,
                        client=self._client,
                    )
                )
        self._last_errors = tuple(failures)
        return items

    def _identity_for(
        self, code: str
    ) -> Optional[Mapping[str, str]]:
        if _BE_ISIN_RE.match(code):
            # A Belgian ISIN typed as the ticker is authoritative on its own.
            return {"name": "", "isin": code}
        identity = self._universe.get(code)
        if not identity:
            return None
        name = str(identity.get("name") or "").strip()
        isin = str(identity.get("isin") or "").strip().upper()
        if not name and not isin:
            return None
        if isin and not _BE_ISIN_RE.match(isin):
            # Only Belgian ISINs are queried; a foreign ISIN in the cache
            # must not leak into the STORI search.
            return None
        if name and len(name) < 3:
            return None
        return {"name": name, "isin": isin}


def _default_universe() -> Mapping[str, Mapping[str, str]]:
    """Return the BE universe name map when BE-2 has landed; empty otherwise.

    BE-1 lands before the BE universe cache (BE-2). Once
    ``universe.be_universe`` exists, mnemonic tickers automatically gain an
    ISIN/name identity and STORI matching activates; until then they are
    honestly skipped in ``last_errors``.
    """
    try:
        from ...universe.be_universe import be_universe_name_map
    except ImportError:
        return {}
    return be_universe_name_map()


def _map_record(
    record: Mapping[str, Any],
    *,
    ticker: str,
    identity: Mapping[str, str],
    collected_at: datetime,
    client: StoriClient,
) -> InformationItem:
    documents = tuple(record.get("main_documents") or ())
    first = documents[0] if documents else None
    if first and str(first.get("file_data_id") or "").strip():
        url = client.download_url(str(first["file_data_id"]))
    else:
        url = DEFAULT_PUBLIC_PORTAL
    isin = str(identity.get("isin") or "").strip()
    metadata_isin_codes = tuple(record.get("isin_codes") or ())
    return InformationItem(
        source="fsma_stori",
        source_type="regulatory_filing",
        external_id=str(record["external_id"]),
        tickers=(ticker,),
        issuer=str(record.get("company") or ticker),
        published_at=record["published"],
        title=str(record["title"]),
        document_type=str(record["document_type"]),
        url=url,
        collected_at=collected_at,
        raw_metadata={
            "provider": "fsma_stori",
            "stock_code": ticker,
            "isin": isin,
            "company_name": str(record.get("company") or ""),
            "company_number": str(record.get("company_number") or ""),
            "lei": str(record.get("lei") or ""),
            "isin_codes": metadata_isin_codes,
            "document_titles": tuple(
                str(doc.get("title") or "") for doc in documents
            ),
        },
        market=MARKET_BE,
        summary=None,
        effective_at=record["published"],
    )

