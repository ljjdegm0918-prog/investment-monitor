"""Substack publication-whitelist LIVE connector (article/news metadata).

Spike 2026-08-11 (tests/fixtures/substack/SPIKE.md): Substack is an author
newsletter platform, NOT a ticker forum. There is no public ticker search API,
no ticker tag system, and no per-ticker community surface. The only stable
public surface is per-publication RSS (``/feed``) and archive JSON
(``/api/v1/archive``), both login-free on active publications.

This connector polls a **whitelist** of active Substack newsletters, filters
by America/New_York calendar day, and optionally matches ticker keywords
client-side (best-effort, with false-positive/negative caveats — see SPIKE).
Category is newsletter article/news **metadata**, not forum/discussion posts.

No structured ticker binding: coverage depends on whitelist quality and
keyword match quality. Whitelist requires maintenance against off-platform
publication migration (e.g., thediff migrated to thediff.co).
"""

from __future__ import annotations

import logging
from datetime import date, datetime, timezone
from typing import Callable, List, Optional, Sequence, Tuple
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

from ...models import MARKET_US, CollectionRequest, InformationItem
from .parser import SubstackFeedRow, new_york_day, parse_substack_rss

LOGGER = logging.getLogger(__name__)
NEW_YORK = ZoneInfo("America/New_York")
FEED_URL_TEMPLATE = "https://{publication}/feed"
DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (compatible; InvestmentMonitor/0.1; +https://example.local)"
)

# Default whitelist of active, real newsletters (cross-checked 2026-08-11).
# Publications may migrate off-platform; whitelist requires maintenance.
DEFAULT_PUBLICATIONS: Tuple[str, ...] = (
    "noahpinion.blog",
    "notboring.co",
    "astralcodexten.com",
    "paulkrugman.substack.com",
    "oneusefulthing.org",
)


class SubstackRequestError(RuntimeError):
    """Raised when a single publication feed fetch fails."""


class SubstackConnector:
    """Substack publication-whitelist LIVE connector.

    Polls public RSS feeds for a whitelist of active Substack publications,
    filters by America/New_York calendar day. Ticker binding is via optional
    client-side keyword matching (best-effort, not structured — see SPIKE.md).
    """

    name = "substack"
    provider = "Substack"
    status = "live"

    def __init__(
        self,
        *,
        publications: Sequence[str] = DEFAULT_PUBLICATIONS,
        user_agent: str = DEFAULT_USER_AGENT,
        fetch_rss: Optional[Callable[[str], str]] = None,
    ) -> None:
        self._publications = tuple(publications)
        self._user_agent = user_agent
        self._fetch_rss = fetch_rss or self._fetch_publication_feed
        self._last_errors: Tuple[Tuple[str, str], ...] = ()

    @property
    def last_errors(self) -> Tuple[Tuple[str, str], ...]:
        return self._last_errors

    def collect(self, request: CollectionRequest) -> List[InformationItem]:
        items: List[InformationItem] = []
        failures: List[Tuple[str, str]] = []
        collected_at = datetime.now(timezone.utc)
        # Substack is a US-only community source: only match US tickers so a
        # non-US ticker is never keyword-bound to a ``market=us`` item.
        us_tickers = tuple(
            ticker
            for ticker in request.tickers
            if request.market_for(ticker) == MARKET_US
        )
        if not us_tickers:
            return items

        for publication in self._publications:
            try:
                rss_text = self._fetch_rss(publication)
                day = request.start_date
                while day <= request.end_date:
                    rows = parse_substack_rss(rss_text, on_date=day)
                    for row in rows:
                        matched = self._match_tickers(row, us_tickers)
                        if not matched:
                            continue
                        items.append(
                            self._map_row(row, publication, matched, collected_at)
                        )
                    day = date.fromordinal(day.toordinal() + 1)
            except Exception as error:
                message = str(error) or error.__class__.__name__
                failures.append((publication, message))
                LOGGER.warning(
                    "substack publication=%s status=failure error=%s",
                    publication,
                    message,
                )

        self._last_errors = tuple(failures)
        return items

    @staticmethod
    def _match_tickers(
        row: SubstackFeedRow,
        tickers: Tuple[str, ...],
    ) -> Tuple[str, ...]:
        """Best-effort keyword match of tickers against title + summary.

        Caveat (SPIKE 2026-08-11): substring match has false positives
        (``Apple`` matches fruit) and false negatives (company mentioned by
        name only, e.g., ``NVIDIA`` not ``NVDA``). This is not a structured
        ticker filter.
        """
        if not tickers:
            return ()
        text = f"{row.title} {row.summary or ''}".lower()
        return tuple(t for t in tickers if t.lower() in text)

    def _map_row(
        self,
        row: SubstackFeedRow,
        publication: str,
        tickers: Tuple[str, ...],
        collected_at: datetime,
    ) -> InformationItem:
        return InformationItem(
            source=self.name,
            source_type="community",
            external_id=f"substack-{row.post_id}",
            tickers=tickers,
            issuer=publication,
            published_at=row.published_at.astimezone(timezone.utc),
            title=row.title,
            document_type="community_post",
            url=row.url,
            collected_at=collected_at,
            raw_metadata={
                "provider": "substack",
                "publication": publication,
                "category": "newsletter_article",
                "feed_url": FEED_URL_TEMPLATE.format(publication=publication),
                "ny_day": new_york_day(row.published_at).isoformat(),
                "keyword_matched": bool(tickers),
            },
            market=MARKET_US,
            summary=row.summary,
            effective_at=row.published_at.astimezone(timezone.utc),
        )

    def _fetch_publication_feed(self, publication: str) -> str:
        url = FEED_URL_TEMPLATE.format(publication=publication)
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
            raise SubstackRequestError(
                f"substack feed HTTP {error.code} for {publication}"
            ) from error
        except URLError as error:
            raise SubstackRequestError(
                f"substack feed network error for {publication}: {error.reason}"
            ) from error
