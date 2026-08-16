"""Shared models used by every connector and pipeline stage."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any, Mapping, Optional, Tuple


ALLOWED_MARKETS = frozenset({"us", "cn", "hk", "jp", "kr", "uk", "tw", "ca", "au", "be", "fr", "de", "nl", "it", "es", "sg", "ch", "pl", "se", "ee", "lv", "lt", "no", "pt", "aq", "cxe", "emf", "trq", "eux", "unknown"})
MARKET_UNKNOWN = "unknown"
MARKET_US = "us"
MARKET_CN = "cn"
MARKET_HK = "hk"
MARKET_KR = "kr"
MARKET_UK = "uk"
MARKET_JP = "jp"
MARKET_TW = "tw"
MARKET_CA = "ca"
MARKET_AU = "au"
MARKET_BE = "be"
MARKET_FR = "fr"
MARKET_DE = "de"
MARKET_NL = "nl"
MARKET_IT = "it"
MARKET_ES = "es"
MARKET_SG = "sg"
MARKET_CH = "ch"
MARKET_PL = "pl"
MARKET_SE = "se"
MARKET_AQ = "aq"
MARKET_CXE = "cxe"
MARKET_EMF = "emf"
MARKET_TRQ = "trq"
MARKET_EUX = "eux"
MARKET_EE = "ee"
MARKET_LV = "lv"
MARKET_LT = "lt"
MARKET_NO = "no"
MARKET_PT = "pt"


@dataclass(frozen=True)
class CollectionRequest:
    """The tickers and inclusive date range that connectors should collect."""

    tickers: Tuple[str, ...]
    start_date: date
    end_date: date
    markets: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        normalized_tickers = tuple(
            ticker.strip().upper() for ticker in self.tickers if ticker.strip()
        )
        if not normalized_tickers:
            raise ValueError("At least one ticker is required.")
        if self.start_date > self.end_date:
            raise ValueError("start_date must not be after end_date.")
        normalized_markets = {
            ticker.strip().upper(): market.strip().lower()
            for ticker, market in self.markets.items()
            if ticker.strip()
        }
        invalid_markets = [
            market
            for market in normalized_markets.values()
            if market not in ALLOWED_MARKETS
        ]
        if invalid_markets:
            raise ValueError(
                "market must be one of: "
                + ", ".join(sorted(ALLOWED_MARKETS))
                + f"; got {invalid_markets[0]!r}"
            )
        object.__setattr__(self, "tickers", normalized_tickers)
        object.__setattr__(self, "markets", normalized_markets)

    def market_for(self, ticker: str) -> str:
        """Return the declared market for a ticker, or unknown when absent."""
        return self.markets.get(ticker.strip().upper(), MARKET_UNKNOWN)


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
    market: str = MARKET_UNKNOWN
    summary: Optional[str] = None
    effective_at: Optional[datetime] = None

    def __post_init__(self) -> None:
        normalized_market = self.market.strip().lower()
        if normalized_market not in ALLOWED_MARKETS:
            raise ValueError(
                "market must be one of: "
                + ", ".join(sorted(ALLOWED_MARKETS))
                + f"; got {self.market!r}"
            )
        object.__setattr__(self, "market", normalized_market)
