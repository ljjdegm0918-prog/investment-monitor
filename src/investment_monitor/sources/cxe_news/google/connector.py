"""Google News (CXE) connector for market=cxe companies."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Callable, List, Mapping, Optional, Tuple

from ....models import CollectionRequest, InformationItem, MARKET_CXE
from ....web_repository import normalize_cxe_ticker
from .client import (
    GoogleCxeNewsClient,
    GoogleCxeNewsRequestError,
)

LOGGER = logging.getLogger(__name__)

MAX_LOOKBACK_DAYS = 30


class GoogleCxeNewsConnector:
    """Collect Google News RSS items for market=cxe companies.

    Yahoo Finance has no suffix for Cboe Europe symbols (live verified
    2026-08-10), so Google News is the only wired news source. Queries
    prefer the exact company name from the CXE universe cache (via the
    injectable ``name_for``) and fall back to the Cboe symbol when no
    name is known; results may be loosely related.
    """

    name = "google_news_cxe"
    provider = "Google News (CXE)"
    max_lookback_days = MAX_LOOKBACK_DAYS

    def __init__(
        self,
        client: Optional[GoogleCxeNewsClient] = None,
        name_for: Optional[Callable[[str], Optional[str]]] = None,
    ) -> None:
        self._client = client or GoogleCxeNewsClient.from_environment()
        self._name_for = name_for or _default_name_for
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
            if market != MARKET_CXE:
                continue
            code = normalize_cxe_ticker(ticker)
            name = self._name_for(code)
            query = f'"{name}"' if name else code
            try:
                records = self._client.fetch_news(
                    query,
                    request.start_date,
                    request.end_date,
                )
                items.extend(
                    _map_news(
                        records,
                        code=code,
                        query=query,
                        collected_at=collected_at,
                    )
                )
            except Exception as error:
                message = str(error) or error.__class__.__name__
                failures.append((ticker, message))
                LOGGER.warning(
                    "google_news_cxe ticker=%s status=failure error=%s",
                    ticker,
                    message,
                )
        self._last_errors = tuple(failures)
        if len(request.tickers) == 1 and failures:
            raise GoogleCxeNewsRequestError(failures[0][1])
        return items


def _default_name_for(ticker: str) -> Optional[str]:
    """Company name from the CXE universe cache, or None when absent."""
    try:
        from ....universe.cxe_universe import cxe_universe_name_map
    except ImportError:
        return None
    identity = cxe_universe_name_map().get(ticker)
    if not identity:
        return None
    name = str(identity.get("name") or "").strip()
    return name or None


def _map_news(
    records: List[Mapping[str, Any]],
    *,
    code: str,
    query: str,
    collected_at: datetime,
) -> List[InformationItem]:
    items: List[InformationItem] = []
    for record in records:
        items.append(
            InformationItem(
                source="google_news_cxe",
                source_type="news",
                external_id=str(record["external_id"]),
                tickers=(code,),
                issuer=code,
                published_at=record["published"],
                title=str(record["title"]),
                document_type="news",
                url=str(record["url"]),
                collected_at=collected_at,
                raw_metadata={
                    "provider": "google_news_rss",
                    "stock_code": code,
                    "query": query,
                    "langs": "en-GB",
                    "scraped": True,
                },
                market=MARKET_CXE,
                summary=record.get("summary"),
                effective_at=record["published"],
            )
        )
    return items
