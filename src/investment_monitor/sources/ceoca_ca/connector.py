"""CEO.ca (Canada) community connector — live JSON API."""

from __future__ import annotations

import json
import logging
from datetime import date, datetime, timedelta, timezone
from typing import Any, Callable, List, Mapping, Optional, Sequence, Tuple
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

from ...models import MARKET_CA, CollectionRequest, InformationItem
from ...web_repository import normalize_ca_ticker
from .parser import (
    CeocaSpielRow,
    MAX_SUMMARY_LEN,
    filter_spiels_to_toronto_day,
    spiel_title,
    toronto_day_from_ms,
)

LOGGER = logging.getLogger(__name__)
TORONTO = ZoneInfo("America/Toronto")

API_BASE = "https://new-api.ceo.ca/api/get_spiels"
CHANNEL_URL_TEMPLATE = "https://ceo.ca/{channel}"
DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (compatible; InvestmentMonitor/0.1; +https://example.local)"
)
DEFAULT_PAGE_LIMIT = 100
# SPIKE 2026-08-11: new-api.ceo.ca ignores the `limit` param and always
# returns exactly 50 spiels per page. Break-on-short-page must compare
# against this real page size, not the requested `limit`.
CEO_CA_PAGE_SIZE = 50
MAX_PAGES = 50


class CeocaRequestError(RuntimeError):
    """Raised when a single-ticker CEO.ca fetch fails."""


class CeocaCaConnector:
    """CA community source for CEO.ca public channel spiels."""

    name = "ceoca_ca"
    provider = "CEO.ca"
    status = "live"

    def __init__(
        self,
        *,
        user_agent: str = DEFAULT_USER_AGENT,
        page_limit: int = DEFAULT_PAGE_LIMIT,
        fetch_json: Optional[
            Callable[[str, str, Optional[int]], Mapping[str, Any]]
        ] = None,
    ) -> None:
        self._user_agent = user_agent
        self._page_limit = page_limit
        self._fetch_json = fetch_json or self._fetch_spiels_page
        self._last_errors: Tuple[Tuple[str, str], ...] = ()

    @property
    def last_errors(self) -> Tuple[Tuple[str, str], ...]:
        return self._last_errors

    def collect(self, request: CollectionRequest) -> List[InformationItem]:
        items: List[InformationItem] = []
        failures: List[Tuple[str, str]] = []
        collected_at = datetime.now(timezone.utc)
        for ticker in request.tickers:
            code = normalize_ca_ticker(ticker)
            market = request.market_for(code)
            if market != MARKET_CA:
                LOGGER.info(
                    "ceoca_ca ticker=%s market=%s skipped not_ca_market",
                    ticker,
                    market,
                )
                continue
            channel = code.lower()
            try:
                rows = self._fetch_spiels_for_range(
                    channel,
                    request.start_date,
                    request.end_date,
                )
                items.extend(
                    self.map_rows(
                        rows,
                        ticker=code,
                        collected_at=collected_at,
                    )
                )
            except Exception as error:
                message = str(error) or error.__class__.__name__
                failures.append((ticker, message))
                LOGGER.warning(
                    "ceoca_ca ticker=%s status=failure error=%s",
                    ticker,
                    message,
                )
        self._last_errors = tuple(failures)
        if len(request.tickers) == 1 and failures:
            raise CeocaRequestError(failures[0][1])
        return items

    def map_rows(
        self,
        rows: Sequence[CeocaSpielRow],
        *,
        ticker: str,
        collected_at: Optional[datetime] = None,
    ) -> List[InformationItem]:
        """Map parsed spiel rows to InformationItems."""
        code = normalize_ca_ticker(ticker)
        channel = code.lower()
        collected = collected_at or datetime.now(timezone.utc)
        channel_url = CHANNEL_URL_TEMPLATE.format(channel=code.upper())
        items: List[InformationItem] = []
        for row in rows:
            title = spiel_title(row.body, author=row.author)
            summary = (row.body or "")[:MAX_SUMMARY_LEN] or None
            items.append(
                InformationItem(
                    source=self.name,
                    source_type="community",
                    external_id=f"ceoca-{row.spiel_id}",
                    tickers=(code,),
                    issuer=code,
                    published_at=row.published_at.astimezone(timezone.utc),
                    title=title,
                    document_type="community_post",
                    url=channel_url,
                    collected_at=collected,
                    raw_metadata={
                        "provider": "ceo_ca",
                        "spiel_id": row.spiel_id,
                        "stock_code": code,
                        "channel": channel,
                        "author": row.author,
                        "channel_url": channel_url,
                        "url_pattern": "https://ceo.ca/{CHANNEL}",
                    },
                    market=MARKET_CA,
                    summary=summary,
                    effective_at=row.published_at.astimezone(timezone.utc),
                )
            )
        return items

    def _fetch_spiels_for_range(
        self,
        channel: str,
        start_date: date,
        end_date: date,
    ) -> List[CeocaSpielRow]:
        """Paginate CEO.ca spiels until the Toronto day range is covered."""
        if start_date > end_date:
            return []
        collected: List[CeocaSpielRow] = []
        until: Optional[int] = None
        for page_index in range(MAX_PAGES):
            payload = self._fetch_json(channel, self._user_agent, until)
            spiels = payload.get("spiels")
            if not isinstance(spiels, list) or not spiels:
                break
            timestamps = [
                int(entry["timestamp"])
                for entry in spiels
                if isinstance(entry, Mapping)
                and entry.get("timestamp") is not None
            ]
            if not timestamps:
                break
            oldest_ms = min(timestamps)
            for day in _date_span(start_date, end_date):
                collected.extend(
                    filter_spiels_to_toronto_day(spiels, on_date=day)
                )
            oldest_day = toronto_day_from_ms(oldest_ms)
            if oldest_day is not None and oldest_day < start_date:
                break
            until = oldest_ms - 1
            # API fixes ~50 spiels/page and ignores `limit`; a short page is
            # the last page. Compare against the real page size (50).
            if len(spiels) < CEO_CA_PAGE_SIZE:
                break
            LOGGER.debug(
                "ceoca_ca channel=%s page=%s until=%s oldest_day=%s",
                channel,
                page_index + 1,
                until,
                oldest_day,
            )
        return _dedupe_rows(collected)

    def _fetch_spiels_page(
        self,
        channel: str,
        user_agent: str,
        until: Optional[int],
    ) -> Mapping[str, Any]:
        params: dict[str, Any] = {
            "channel": channel.lower(),
            "limit": self._page_limit,
        }
        if until is not None:
            params["until"] = until
        url = f"{API_BASE}?{urlencode(params)}"
        request = Request(
            url,
            headers={"User-Agent": user_agent, "Accept": "application/json"},
        )
        try:
            with urlopen(request, timeout=30) as response:
                body = response.read().decode("utf-8")
        except HTTPError as error:
            raise CeocaRequestError(
                f"CEO.ca HTTP {error.code} for channel {channel!r}"
            ) from error
        except URLError as error:
            raise CeocaRequestError(
                f"CEO.ca network error for channel {channel!r}: {error.reason}"
            ) from error
        decoded = json.loads(body)
        if not isinstance(decoded, Mapping):
            raise CeocaRequestError("CEO.ca response is not a JSON object.")
        return decoded


def _date_span(start_date: date, end_date: date) -> List[date]:
    days: List[date] = []
    current = start_date
    while current <= end_date:
        days.append(current)
        current += timedelta(days=1)
    return days


def _dedupe_rows(rows: Sequence[CeocaSpielRow]) -> List[CeocaSpielRow]:
    seen: set[str] = set()
    unique: List[CeocaSpielRow] = []
    for row in rows:
        if row.spiel_id in seen:
            continue
        seen.add(row.spiel_id)
        unique.append(row)
    return unique
