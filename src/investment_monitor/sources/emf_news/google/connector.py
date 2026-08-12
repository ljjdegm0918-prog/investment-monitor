"""Google News (EMF) connector for market=emf funds."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Callable, List, Mapping, Optional, Tuple

from ....models import CollectionRequest, InformationItem, MARKET_EMF
from ....web_repository import normalize_emf_ticker
from .client import (
    GoogleEmfNewsClient,
    GoogleEmfNewsRequestError,
)

LOGGER = logging.getLogger(__name__)

MAX_LOOKBACK_DAYS = 30


class GoogleEmfNewsConnector:
    """Collect Google News RSS items for market=emf funds.

    Yahoo Finance has no stable symbol suffix for European mutual funds
    (live verified 2026-08-10), so Google News is the only wired news
    source. Queries prefer the fund name from the injectable ``name_for``
    (default: a manually placed EMF universe cache) and fall back to the
    typed fund ISIN when no name is known; ISIN queries are usually
    sparse, which is documented honestly.
    """

    name = "google_news_emf"
    provider = "Google News (EMF)"
    max_lookback_days = MAX_LOOKBACK_DAYS

    def __init__(
        self,
        client: Optional[GoogleEmfNewsClient] = None,
        name_for: Optional[Callable[[str], Optional[str]]] = None,
    ) -> None:
        self._client = client or GoogleEmfNewsClient.from_environment()
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
            if market != MARKET_EMF:
                continue
            code = normalize_emf_ticker(ticker)
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
                    "google_news_emf ticker=%s status=failure error=%s",
                    ticker,
                    message,
                )
        self._last_errors = tuple(failures)
        if len(request.tickers) == 1 and failures:
            raise GoogleEmfNewsRequestError(failures[0][1])
        return items


def _default_name_for(ticker: str) -> Optional[str]:
    """Fund name from a manually placed EMF universe cache, or None."""
    try:
        from ....universe.emf_universe import emf_universe_name_map
    except ImportError:
        return None
    identity = emf_universe_name_map().get(ticker)
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
                source="google_news_emf",
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
                    "fund_isin": code,
                    "query": query,
                    "langs": "en-GB",
                    "scraped": True,
                },
                market=MARKET_EMF,
                summary=record.get("summary"),
                effective_at=record["published"],
            )
        )
    return items
