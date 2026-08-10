"""GPW ESPI/EBI connector for market=pl companies.

Collects official GPW ESPI/EBI reports from ``www.gpw.pl/komunikaty``.
Matching is by Polish ISIN: from the PL universe cache when available, or
a Polish ISIN typed directly as the ticker (mirrors the EQS rail). A
requested PL ticker without an ISIN is skipped honestly and recorded in
``last_errors`` (never a fake success).
"""

from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from typing import Any, List, Mapping, Optional, Tuple

from ...models import CollectionRequest, InformationItem, MARKET_PL
from ...web_repository import normalize_pl_ticker
from .client import (
    GpwEspiClient,
    GpwEspiRequestError,
)

LOGGER = logging.getLogger(__name__)

MAX_LOOKBACK_DAYS = 30
_PL_ISIN_RE = re.compile(r"^PL[0-9A-Z]{10}$")


class GpwEspiConnector:
    """Collect official GPW ESPI/EBI reports for market=pl companies.

    Matching is by Polish ISIN: from the PL universe cache by default
    (loaded lazily through ``pl_universe_name_map()``), or a Polish ISIN
    typed directly as the ticker. The GPW reports list shows issuer name +
    ISIN, not ticker mnemonics, so a company without any ISIN identity is
    skipped honestly with a ``no_universe_identity`` last_error instead of
    guessing.
    """

    name = "gpw_espi"
    provider = "GPW ESPI/EBI (official reports page)"
    max_lookback_days = MAX_LOOKBACK_DAYS

    def __init__(
        self,
        client: Optional[GpwEspiClient] = None,
        universe: Optional[Mapping[str, Mapping[str, str]]] = None,
    ) -> None:
        self._client = client or GpwEspiClient.from_environment()
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
        items: List[InformationItem] = []
        failures: List[Tuple[str, str]] = []
        collected_at = datetime.now(timezone.utc)
        for ticker in request.tickers:
            market = request.market_for(ticker)
            if market != MARKET_PL:
                LOGGER.info(
                    "gpw_espi ticker=%s market=%s skipped not_pl_market",
                    ticker,
                    market,
                )
                continue
            code = normalize_pl_ticker(ticker)
            isin = self._isin_for(code)
            if not isin:
                failures.append((ticker, "no_universe_identity"))
                LOGGER.info(
                    "gpw_espi ticker=%s skipped no_universe_identity",
                    ticker,
                )
                continue
            try:
                records = self._client.fetch_reports(
                    isin,
                    request.start_date,
                    request.end_date,
                )
                items.extend(
                    _map_filings(
                        records,
                        code=code,
                        collected_at=collected_at,
                    )
                )
            except Exception as error:
                message = str(error) or error.__class__.__name__
                failures.append((ticker, message))
                LOGGER.warning(
                    "gpw_espi ticker=%s status=failure error=%s",
                    ticker,
                    message,
                )
        self._last_errors = tuple(failures)
        if len(request.tickers) == 1 and failures:
            raise GpwEspiRequestError(failures[0][1])
        return items

    def _isin_for(self, code: str) -> Optional[str]:
        if _PL_ISIN_RE.match(code):
            return code
        identity = self._universe.get(code)
        if not identity:
            return None
        isin = str(identity.get("isin") or "").strip().upper()
        if _PL_ISIN_RE.match(isin):
            return isin
        return None


def _map_filings(
    records: List[Mapping[str, Any]],
    *,
    code: str,
    collected_at: datetime,
) -> List[InformationItem]:
    items: List[InformationItem] = []
    for record in records:
        report_type = str(record.get("report_type") or "").lower()
        report_number = str(record.get("report_number") or "")
        items.append(
            InformationItem(
                source="gpw_espi",
                source_type="regulatory_filing",
                external_id=str(record["external_id"]),
                tickers=(code,),
                issuer=str(record.get("company_name") or code),
                published_at=record["published"],
                title=str(record["title"]),
                document_type=(
                    f"{report_type}_{report_number}"
                    if report_number
                    else report_type or "espi"
                ),
                url=str(record["url"]),
                collected_at=collected_at,
                raw_metadata={
                    "provider": "gpw_komunikaty_page",
                    "isin": str(record.get("isin") or ""),
                    "report_type": str(record.get("report_type") or ""),
                    "report_number": report_number,
                    "company_name": str(record.get("company_name") or ""),
                },
                market=MARKET_PL,
                effective_at=record["published"],
            )
        )
    return items


def _default_universe() -> Mapping[str, Mapping[str, str]]:
    """Return the PL universe name map (the default connector identity)."""
    try:
        from ...universe.pl_universe import pl_universe_name_map
    except ImportError:
        return {}
    return pl_universe_name_map()
