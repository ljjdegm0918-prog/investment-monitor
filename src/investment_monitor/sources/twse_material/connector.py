"""TWSE OpenAPI material-information connector for market=tw companies."""

from __future__ import annotations

import logging
from datetime import date, datetime, timezone
from typing import Any, List, Mapping, Optional, Tuple

from ...models import CollectionRequest, InformationItem, MARKET_TW
from .client import (
    MOPS_QUERY_URL,
    TwseMaterialClient,
    TwseMaterialRequestError,
    normalize_tw_ticker,
)

LOGGER = logging.getLogger(__name__)

MAX_LOOKBACK_DAYS = 30


class TwseMaterialConnector:
    """Collect TWSE listed-company material announcements for market=tw."""

    name = "twse_material"
    provider = "TWSE OpenAPI (material)"
    max_lookback_days = MAX_LOOKBACK_DAYS
    # Key-free: no secret_fields and no configuration_error.

    def __init__(self, client: Optional[TwseMaterialClient] = None) -> None:
        self._client = client or TwseMaterialClient.from_environment()
        self._last_errors: Tuple[Tuple[str, str], ...] = ()

    @property
    def last_errors(self) -> Tuple[Tuple[str, str], ...]:
        """(ticker, message) pairs from the most recent collect call."""
        return self._last_errors

    def collect(self, request: CollectionRequest) -> List[InformationItem]:
        """Collect material notices for the request's TW tickers."""
        tw_tickers = [
            normalize_tw_ticker(ticker)
            for ticker in request.tickers
            if request.market_for(ticker) == MARKET_TW
        ]
        if not tw_tickers:
            self._last_errors = ()
            return []
        try:
            records = self._client.fetch_material()
        except Exception as error:
            message = str(error) or error.__class__.__name__
            failures = tuple((ticker, message) for ticker in tw_tickers)
            self._last_errors = failures
            LOGGER.warning(
                "twse_material status=failure error=%s",
                message,
            )
            if len(request.tickers) == 1:
                raise TwseMaterialRequestError(message)
            return []

        wanted = set(tw_tickers)
        collected_at = datetime.now(timezone.utc)
        items: List[InformationItem] = []
        for record in records:
            if record["ticker"] not in wanted:
                continue
            if not (
                request.start_date
                <= date.fromisoformat(record["calendar_date"])
                <= request.end_date
            ):
                continue
            items.append(_map_record(record, collected_at=collected_at))
        self._last_errors = ()
        return items


def _map_record(
    record: Mapping[str, Any],
    *,
    collected_at: datetime,
) -> InformationItem:
    raw_metadata = dict(record["raw"])
    raw_metadata.update(
        {
            "provider": "twse_openapi",
            "api_url": record["api_url"],
            "stock_code": record["ticker"],
            "company_name": record["company_name"],
            "clause": record["clause"],
            "event_date": record["event_date"],
            "date_only": record["date_only"],
            "calendar_date": record["calendar_date"],
        }
    )
    return InformationItem(
        source="twse_material",
        source_type="regulatory_filing",
        external_id=record["external_id"],
        tickers=(record["ticker"],),
        issuer=record["company_name"] or record["ticker"],
        published_at=record["published_at"],
        title=record["title"],
        document_type="tw_material",
        url=MOPS_QUERY_URL,
        collected_at=collected_at,
        raw_metadata=raw_metadata,
        market=MARKET_TW,
        summary=record["summary"],
        effective_at=record["published_at"],
    )
