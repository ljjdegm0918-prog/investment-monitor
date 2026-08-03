"""Shared models used by every connector and pipeline stage."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any, Mapping, Tuple


@dataclass(frozen=True)
class CollectionRequest:
    """The tickers and inclusive date range that connectors should collect."""

    tickers: Tuple[str, ...]
    start_date: date
    end_date: date

    def __post_init__(self) -> None:
        normalized_tickers = tuple(
            ticker.strip().upper() for ticker in self.tickers if ticker.strip()
        )
        if not normalized_tickers:
            raise ValueError("At least one ticker is required.")
        if self.start_date > self.end_date:
            raise ValueError("start_date must not be after end_date.")
        object.__setattr__(self, "tickers", normalized_tickers)


@dataclass(frozen=True)
class InformationItem:
    """A source-independent item that downstream code can safely consume."""

    source: str
    source_type: str
    external_id: str
    tickers: Tuple[str, ...]
    issuer: str
    published_at: datetime
    title: str
    document_type: str
    url: str
    collected_at: datetime
    raw_metadata: Mapping[str, Any] = field(default_factory=dict)

