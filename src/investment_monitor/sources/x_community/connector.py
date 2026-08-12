"""X (Twitter) community connector with official API fallback."""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass
from datetime import date, datetime, timezone
from typing import Any, Callable, List, Mapping, Optional, Tuple
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

from ...connectors.base import ConnectorUnavailableError, SecretField
from ...models import MARKET_US, CollectionRequest, InformationItem

LOGGER = logging.getLogger(__name__)
NEW_YORK = ZoneInfo("America/New_York")
API_BASE = "https://api.x.com/2/tweets/search/recent"
DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (compatible; InvestmentMonitor/0.1; +https://example.local)"
)

SEARCH_URL = "https://x.com/search?q=%24TICKER&f=live"
COMMUNITIES_URL = "https://x.com/i/communities"


class XCommunityAPIError(RuntimeError):
    """Raised when the official X API cannot satisfy a request."""


@dataclass(frozen=True)
class XCommunityResult:
    """Normalized X post data for downstream consumption."""

    external_id: str
    created_at: datetime
    text: str
    deeplink: str
    community_id: Optional[str]
    cashtags: Tuple[str, ...]


def _new_york_day(value: datetime) -> date:
    return value.astimezone(NEW_YORK).date()


def normalize_us_ticker(ticker: str) -> str:
    """Normalize a US equity symbol to its uppercase root form."""
    return str(ticker).strip().upper()


class XCommunityConnector:
    """US community source for X (Twitter) official API search.

    ``status="live"`` when ``X_BEARER_TOKEN`` is present: ``collect()`` uses
    ``GET /2/tweets/search/recent`` with cashtag queries and filters results to
    the requested calendar day in America/New_York. Without a token the
    connector stays honest and records an unavailable reason instead of
    pretending to be live.

    Official X API v2 note: search/recent supports cashtag queries
    (``$TICKER``), ``start_time``/``end_time`` within a 7-day window, and
    returns stable ``id`` / ``created_at`` / ``text`` / ``community_id``.
    """

    name = "x_community"
    provider = "X"
    status = "live"
    secret_fields = (
        SecretField(
            env="X_BEARER_TOKEN",
            label="X Bearer Token",
            kind="password",
            help="Official X API v2 bearer token for search/recent access.",
        ),
    )

    def __init__(
        self,
        *,
        bearer_token: Optional[str] = None,
        fetch_json: Optional[Callable[[str], Mapping[str, Any]]] = None,
        user_agent: str = DEFAULT_USER_AGENT,
    ) -> None:
        token = (bearer_token if bearer_token is not None else os.environ.get("X_BEARER_TOKEN", "")).strip()
        if not token:
            raise ConnectorUnavailableError(
                self.configuration_error() or "X_BEARER_TOKEN is not configured."
            )
        self._bearer_token = token
        self._user_agent = user_agent
        self._fetch_json: Callable[[str], Mapping[str, Any]] = (
            fetch_json or self._fetch_search
        )
        self._last_errors: Tuple[Tuple[str, str], ...] = ()

    @property
    def last_errors(self) -> Tuple[Tuple[str, str], ...]:
        return self._last_errors

    @classmethod
    def from_environment(cls) -> "XCommunityConnector":
        configuration_error = cls.configuration_error()
        if configuration_error is not None:
            raise ConnectorUnavailableError(configuration_error)
        return cls()

    @classmethod
    def configuration_error(cls) -> Optional[str]:
        if not os.environ.get("X_BEARER_TOKEN", "").strip():
            return "X_BEARER_TOKEN is not configured; X is not connected."
        return None

    def collect(self, request: CollectionRequest) -> List[InformationItem]:
        """Collect official X API results for each US ticker."""
        items: List[InformationItem] = []
        failures: List[Tuple[str, str]] = []
        collected_at = datetime.now(timezone.utc)
        for ticker in request.tickers:
            market = request.market_for(ticker)
            if market != MARKET_US:
                LOGGER.info(
                    "x_community ticker=%s market=%s skipped not_us_market",
                    ticker,
                    market,
                )
                continue
            code = normalize_us_ticker(ticker)
            try:
                results = self._search_for_ticker(
                    code,
                    request.start_date,
                    request.end_date,
                )
                for result in results:
                    items.append(self._map_result(result, code, collected_at))
            except Exception as error:
                message = str(error) or error.__class__.__name__
                failures.append((code, message))
                LOGGER.warning(
                    "x_community ticker=%s status=failure error=%s",
                    code,
                    message,
                )
            LOGGER.info(
                "x_community ticker=%s status=live items=%s",
                code,
                len(items),
            )
        self._last_errors = tuple(failures)
        return items

    def _search_for_ticker(
        self,
        ticker: str,
        start_date: date,
        end_date: date,
    ) -> List[XCommunityResult]:
        query = f"${ticker} -is:retweet"
        params = {
            "query": query,
            "tweet.fields": "created_at,entities,author_id",
            "expansions": "entities.mentions.username",
            "max_results": 100,
            "sort_order": "recency",
            "start_time": self._to_utc_iso(start_date, start=True),
            "end_time": self._to_utc_iso(end_date, start=False),
        }
        payload = self._fetch_json(f"{API_BASE}?{urlencode(params)}")
        data = payload.get("data", [])
        includes = payload.get("includes", {})
        if not isinstance(data, list):
            raise XCommunityAPIError("X API response missing data array.")
        results: List[XCommunityResult] = []
        for entry in data:
            if not isinstance(entry, Mapping):
                continue
            created_at = self._parse_created_at(str(entry.get("created_at", "")))
            if created_at is None:
                continue
            if _new_york_day(created_at) < start_date or _new_york_day(created_at) > end_date:
                continue
            entities = entry.get("entities") or {}
            cashtags = tuple(
                str(tag.get("tag", "")).upper()
                for tag in (entities.get("cashtags", []) if isinstance(entities, Mapping) else [])
                if isinstance(tag, Mapping) and tag.get("tag")
            )
            results.append(
                XCommunityResult(
                    external_id=str(entry.get("id", "")).strip(),
                    created_at=created_at,
                    text=str(entry.get("text", "")).strip(),
                    deeplink=f"https://x.com/i/web/status/{str(entry.get('id', '')).strip()}",
                    community_id=self._community_id_from_entry(entry)
                    or self._community_id_from_includes(includes),
                    cashtags=cashtags,
                )
            )
        return results

    def _fetch_search(self, url: str) -> Mapping[str, Any]:
        request = Request(
            url,
            headers={
                "Authorization": f"Bearer {self._bearer_token}",
                "User-Agent": self._user_agent,
                "Accept": "application/json",
            },
        )
        try:
            with urlopen(request, timeout=30) as response:
                return json.loads(response.read().decode("utf-8"))
        except HTTPError as error:
            raise XCommunityAPIError(
                f"x_community API HTTP {error.code} for {url}"
            ) from error
        except URLError as error:
            raise XCommunityAPIError(
                f"x_community API network error for {url}: {error.reason}"
            ) from error

    def _map_result(
        self,
        result: XCommunityResult,
        ticker: str,
        collected_at: datetime,
    ) -> InformationItem:
        return InformationItem(
            source=self.name,
            source_type="community",
            external_id=f"x-{result.external_id}",
            tickers=(ticker,),
            issuer="X",
            published_at=result.created_at.astimezone(timezone.utc),
            title=result.text[:120] or ticker,
            document_type="community_post",
            url=result.deeplink,
            collected_at=collected_at,
            raw_metadata={
                "provider": "x",
                "community_id": result.community_id,
                "cashtags": result.cashtags,
                "deeplink": result.deeplink,
                "api": "search/recent",
                "query_ticker": ticker,
                "ny_day": _new_york_day(result.created_at).isoformat(),
            },
            market=MARKET_US,
            summary=result.text,
            effective_at=result.created_at.astimezone(timezone.utc),
        )

    @staticmethod
    def _parse_created_at(value: str) -> Optional[datetime]:
        if not value:
            return None
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None

    @staticmethod
    def _community_id_from_includes(includes: Mapping[str, Any]) -> Optional[str]:
        communities = includes.get("communities") if isinstance(includes, Mapping) else None
        if not isinstance(communities, list):
            return None
        for entry in communities:
            if isinstance(entry, Mapping) and entry.get("id"):
                return str(entry["id"]).strip()
        return None

    @staticmethod
    def _community_id_from_entry(entry: Mapping[str, Any]) -> Optional[str]:
        attachments = entry.get("attachments")
        if not isinstance(attachments, Mapping):
            return None
        community_id = attachments.get("community_id")
        if community_id is None:
            return None
        return str(community_id).strip() or None

    @staticmethod
    def _to_utc_iso(day: date, *, start: bool) -> str:
        hour = 0 if start else 23
        minute = 0 if start else 59
        second = 0 if start else 59
        moment = datetime(day.year, day.month, day.day, hour, minute, second, tzinfo=NEW_YORK)
        return moment.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
