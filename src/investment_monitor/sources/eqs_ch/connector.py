"""EQS News (CH) regulatory disclosures for market=ch companies.

Collects Swiss issuer disclosures from the key-free EQS News JSON API
(``/wp-json/eqsnews/v1/news?isin=...``). Matching is by Swiss ISIN (from
the CH universe cache once it exists, or a Swiss ISIN typed as the ticker).
Requested CH tickers without an ISIN are skipped and recorded in
``last_errors`` (never a fake success). EQS coverage of Swiss ISINs is
partial (Roche/UBS have records; Nestle/Novartis return empty lists); it is
an unofficial public feed, not a SIX/FINMA official source. Dates use
Europe/Zurich day bounds.
"""

from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from typing import List, Mapping, Optional, Tuple

from ...models import CollectionRequest, InformationItem, MARKET_CH
from ...web_repository import normalize_ch_ticker
from .client import (
    EqsChClient,
    EqsChRequestError,
    zurich_day,
)

LOGGER = logging.getLogger(__name__)

MAX_LOOKBACK_DAYS = 30
_CH_ISIN_RE = re.compile(r"^CH[0-9A-Z]{10}$")


class EqsChConnector:
    """Collect EQS News disclosures for market=ch companies."""

    name = "eqs_ch"
    provider = "EQS News (CH)"
    max_lookback_days = MAX_LOOKBACK_DAYS

    def __init__(
        self,
        client: Optional[EqsChClient] = None,
        universe: Optional[Mapping[str, Mapping[str, str]]] = None,
    ) -> None:
        self._client = client or EqsChClient.from_environment()
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
        jobs: List[Tuple[str, str]] = []
        for ticker in request.tickers:
            if request.market_for(ticker) != MARKET_CH:
                LOGGER.info(
                    "eqs_ch ticker=%s market=%s skipped not_ch_market",
                    ticker,
                    request.market_for(ticker),
                )
                continue
            code = normalize_ch_ticker(ticker)
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
                    "eqs_ch ticker=%s status=failure error=%s",
                    code,
                    message,
                )
                if len(request.tickers) == 1:
                    self._last_errors = tuple(failures)
                    raise EqsChRequestError(message) from error
                continue
            for record in records:
                day = zurich_day(record["published_at"])
                if day < request.start_date or day > request.end_date:
                    continue
                items.append(
                    InformationItem(
                        source="eqs_ch",
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
                        market=MARKET_CH,
                        summary=None,
                        effective_at=record["published_at"],
                    )
                )
        self._last_errors = tuple(failures)
        return items

    def _isin_for(self, code: str) -> Optional[str]:
        if _CH_ISIN_RE.match(code):
            return code
        identity = self._universe.get(code)
        if not identity:
            return None
        isin = str(identity.get("isin") or "").strip().upper()
        if _CH_ISIN_RE.match(isin):
            return isin
        return None


def _default_universe() -> Mapping[str, Mapping[str, str]]:
    """Return the CH universe name map when CH-2 has landed; empty otherwise."""
    try:
        from ...universe.ch_universe import ch_universe_name_map
    except ImportError:
        return {}
    return ch_universe_name_map()
