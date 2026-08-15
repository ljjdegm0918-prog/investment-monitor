"""Source-wide official Eurex circulars and newsflashes."""

from __future__ import annotations

from datetime import datetime, time, timezone
from typing import List
from zoneinfo import ZoneInfo

from ...models import CollectionRequest, InformationItem, MARKET_EUX
from ...provenance import build_raw_provenance
from .client import EurexCircularsClient

FRANKFURT = ZoneInfo("Europe/Berlin")


class EurexCircularsConnector:
    name = "eurex_circulars"
    provider = "Eurex Circulars & Newsflashes (official)"
    source_wide_collection = True
    max_lookback_days = 365

    def __init__(self, client: EurexCircularsClient | None = None) -> None:
        self._client = client or EurexCircularsClient()

    def collect(self, request: CollectionRequest) -> List[InformationItem]:
        tickers = tuple(ticker for ticker in request.tickers if request.market_for(ticker) == MARKET_EUX)
        if not tickers:
            return []
        records = self._client.fetch(request.start_date, request.end_date)
        collected_at = datetime.now(timezone.utc)
        items: List[InformationItem] = []
        for record in records:
            published = datetime.combine(record["date"], time.min, tzinfo=FRANKFURT)
            tagline = str(record["tagline"])
            categories = [part.strip() for part in tagline.split("|") if part.strip()]
            url = str(record["url"])
            items.append(
                InformationItem(
                    source=self.name,
                    source_type="regulatory_filing",
                    external_id=str(record["external_id"]),
                    tickers=tickers,
                    issuer="Eurex",
                    published_at=published,
                    title=str(record["title"]),
                    document_type="eurex_circular_or_newsflash",
                    url=url,
                    collected_at=collected_at,
                    raw_metadata={
                        **build_raw_provenance(
                            official_source_id=str(record["external_id"]),
                            official_source_url=url,
                            retrieval_url=str(record["retrieval_url"]),
                            raw_payload=record["raw_payload"],
                            raw_payload_format="html_search_result",
                            classification_code=None,
                            classification_label=" | ".join(categories),
                            published_at_raw=str(record["published_at_raw"]),
                            published_timezone="Europe/Berlin",
                        ),
                        "categories": categories,
                    },
                    market=MARKET_EUX,
                    effective_at=published,
                )
            )
        return items
