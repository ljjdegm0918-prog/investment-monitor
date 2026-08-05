"""A deterministic connector for examples and tests."""

from __future__ import annotations

from datetime import datetime, time, timezone
from typing import List

from ..models import CollectionRequest, InformationItem


class MockConnector:
    """Return one predictable item for each requested ticker."""

    name = "mock"

    def collect(self, request: CollectionRequest) -> List[InformationItem]:
        collected_at = datetime.now(timezone.utc)
        published_at = datetime.combine(
            request.start_date, time.min, tzinfo=timezone.utc
        )

        return [
            InformationItem(
                source=self.name,
                source_type="mock",
                external_id=f"mock-{ticker}-{request.start_date.isoformat()}",
                tickers=(ticker,),
                issuer=f"{ticker} Example Issuer",
                published_at=published_at,
                title=f"Mock information item for {ticker}",
                document_type="mock_document",
                url=f"https://example.test/items/{ticker.lower()}",
                collected_at=collected_at,
                raw_metadata={"generated": True},
                market=request.market_for(ticker),
            )
            for ticker in request.tickers
        ]

