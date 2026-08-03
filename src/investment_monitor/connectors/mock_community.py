"""Deterministic community connector used to prove multi-source extensibility."""

from __future__ import annotations

from datetime import datetime, time, timezone
from typing import List

from ..models import CollectionRequest, InformationItem


class MockCommunityConnector:
    """Return one fake community announcement per requested ticker."""

    name = "mock_community"

    def collect(self, request: CollectionRequest) -> List[InformationItem]:
        published_at = datetime.combine(
            request.end_date,
            time(hour=12),
            tzinfo=timezone.utc,
        )
        collected_at = datetime.now(timezone.utc)
        return [
            InformationItem(
                source=self.name,
                source_type="community",
                external_id=(
                    f"mock-community-{ticker}-"
                    f"{request.end_date.isoformat()}"
                ),
                tickers=(ticker,),
                issuer=f"{ticker} Community",
                published_at=published_at,
                title=f"Community announcement for {ticker}",
                document_type="community_post",
                url=(
                    "https://community.example.test/posts/"
                    f"{ticker.lower()}-{request.end_date.isoformat()}"
                ),
                collected_at=collected_at,
                raw_metadata={"generated": True, "engagement": 42},
            )
            for ticker in request.tickers
        ]

