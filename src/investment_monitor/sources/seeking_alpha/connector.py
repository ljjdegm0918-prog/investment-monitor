"""Seeking Alpha US connector — live public combined RSS (article/news).

Spike 2026-08-11: HTML symbol/forum/comments pages return PerimeterX 403.
Public RSS ``https://seekingalpha.com/api/sa/combined/{SYMBOL}.xml`` returns
news + analysis metadata (not forum posts). Category is honest article/news
stream under ``source_type=community``.
"""

from __future__ import annotations

import logging
from datetime import date, datetime, timezone
from typing import Callable, List, Optional, Sequence, Tuple
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

from ...models import MARKET_US, CollectionRequest, InformationItem
from .parser import (
    SeekingAlphaFeedRow,
    new_york_day,
    parse_seeking_alpha_combined_rss,
)

LOGGER = logging.getLogger(__name__)
NEW_YORK = ZoneInfo("America/New_York")
FEED_URL_TEMPLATE = (
    "https://seekingalpha.com/api/sa/combined/{symbol}.xml"
)
DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (compatible; InvestmentMonitor/0.1; +https://example.local)"
)


class SeekingAlphaRequestError(RuntimeError):
    """Raised when a single-ticker Seeking Alpha fetch fails."""


def normalize_us_ticker(ticker: str) -> str:
    """Normalize a US equity symbol to its uppercase root form."""
    return str(ticker).strip().upper()


class SeekingAlphaConnector:
    """US community source for Seeking Alpha public combined RSS."""

    name = "seeking_alpha"
    provider = "Seeking Alpha"
    status = "live"

    def __init__(
        self,
        *,
        user_agent: str = DEFAULT_USER_AGENT,
        fetch_xml: Optional[Callable[[str], str]] = None,
    ) -> None:
        self._user_agent = user_agent
        self._fetch_xml = fetch_xml or self._fetch_combined_feed
        self._last_errors: Tuple[Tuple[str, str], ...] = ()

    @property
    def last_errors(self) -> Tuple[Tuple[str, str], ...]:
        return self._last_errors

    def collect(self, request: CollectionRequest) -> List[InformationItem]:
        items: List[InformationItem] = []
        failures: List[Tuple[str, str]] = []
        collected_at = datetime.now(timezone.utc)
        for ticker in request.tickers:
            code = normalize_us_ticker(ticker)
            market = request.market_for(ticker)
            if market != MARKET_US:
                LOGGER.info(
                    "seeking_alpha ticker=%s market=%s skipped not_us_market",
                    ticker,
                    market,
                )
                continue
            try:
                xml_text = self._fetch_xml(code)
                # Combined feed is a rolling ~30-item window; filter each
                # requested calendar day in New York independently.
                day = request.start_date
                while day <= request.end_date:
                    rows = parse_seeking_alpha_combined_rss(
                        xml_text, on_date=day
                    )
                    items.extend(
                        self.map_rows(
                            rows,
                            ticker=code,
                            collected_at=collected_at,
                        )
                    )
                    day = date.fromordinal(day.toordinal() + 1)
            except Exception as error:
                message = str(error) or error.__class__.__name__
                failures.append((ticker, message))
                LOGGER.warning(
                    "seeking_alpha ticker=%s status=failure error=%s",
                    ticker,
                    message,
                )
        self._last_errors = tuple(failures)
        if len(request.tickers) == 1 and failures:
            raise SeekingAlphaRequestError(failures[0][1])
        return items

    def map_rows(
        self,
        rows: Sequence[SeekingAlphaFeedRow],
        *,
        ticker: str,
        collected_at: Optional[datetime] = None,
    ) -> List[InformationItem]:
        code = normalize_us_ticker(ticker)
        collected = collected_at or datetime.now(timezone.utc)
        items: List[InformationItem] = []
        for row in rows:
            items.append(
                InformationItem(
                    source=self.name,
                    source_type="community",
                    external_id=(
                        f"seeking-alpha-{row.content_kind}-{row.content_id}"
                    ),
                    tickers=(code,),
                    issuer=code,
                    published_at=row.published_at.astimezone(timezone.utc),
                    title=row.title,
                    document_type="community_post",
                    url=row.url,
                    collected_at=collected,
                    raw_metadata={
                        "provider": "seeking_alpha",
                        "content_id": row.content_id,
                        "content_kind": row.content_kind,
                        "stock_code": code,
                        "feed_url": FEED_URL_TEMPLATE.format(symbol=code),
                        "category": "article_news_rss",
                        "ny_day": new_york_day(row.published_at).isoformat(),
                    },
                    market=MARKET_US,
                    summary=row.summary,
                    effective_at=row.published_at.astimezone(timezone.utc),
                )
            )
        return items

    def _fetch_combined_feed(self, symbol: str) -> str:
        url = FEED_URL_TEMPLATE.format(symbol=symbol)
        request = Request(
            url,
            headers={
                "User-Agent": self._user_agent,
                "Accept": "application/rss+xml, application/xml, text/xml, */*",
            },
        )
        try:
            with urlopen(request, timeout=30) as response:
                return response.read().decode("utf-8", "replace")
        except HTTPError as error:
            raise SeekingAlphaRequestError(
                f"seeking_alpha feed HTTP {error.code} for {symbol}"
            ) from error
        except URLError as error:
            raise SeekingAlphaRequestError(
                f"seeking_alpha feed network error for {symbol}: {error.reason}"
            ) from error
