"""Google News discovery for reviewed publishers without a usable direct feed."""

from __future__ import annotations

import hashlib
import html
import logging
import re
import threading
import time
from datetime import date, datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Any, Callable, Dict, List, Mapping, Optional, Tuple
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen
import xml.etree.ElementTree as ElementTree
from zoneinfo import ZoneInfo

from ...models import CollectionRequest, InformationItem
from .client import (
    MAX_RESPONSE_BYTES,
    RETRYABLE_STATUS_CODES,
    _content_length,
    _is_allowed_https_url,
    _read_float,
    _read_int,
    _read_limited,
    _response_url,
)
from .connector import (
    _company_aliases,
    _identity_for,
    _identity_map,
    _matched_aliases,
    _normalize_ticker,
)
from .discovery_profiles import PublisherDiscoveryProfile

LOGGER = logging.getLogger(__name__)
GOOGLE_NEWS_RSS_URL = "https://news.google.com/rss/search"
GOOGLE_NEWS_DOMAINS = ("news.google.com",)
MAX_LOOKBACK_DAYS = 30


class PublisherDiscoveryError(Exception):
    """Base error for publisher-scoped Google News discovery."""


class PublisherDiscoveryRequestError(PublisherDiscoveryError):
    """Raised when Google News discovery cannot be completed."""


class PublisherDiscoveryDataError(PublisherDiscoveryError):
    """Raised when discovery data violates the expected safety contract."""


class PublisherDiscoveryClient:
    """Fetch bounded Google News RSS and verify each result's publisher domain."""

    def __init__(
        self,
        timeout: float = 12.0,
        max_retries: int = 1,
        requests_per_second: float = 1.0,
        user_agent: str = "InvestmentMonitor/0.1 publisher-discovery",
        opener: Callable[..., Any] = urlopen,
        clock: Callable[[], float] = time.monotonic,
        sleeper: Callable[[float], None] = time.sleep,
        max_response_bytes: int = MAX_RESPONSE_BYTES,
        max_records_per_query: int = 25,
    ) -> None:
        if timeout <= 0:
            raise ValueError("Publisher discovery timeout must be greater than zero.")
        if max_retries < 0:
            raise ValueError("Publisher discovery max_retries must not be negative.")
        if requests_per_second <= 0:
            raise ValueError(
                "Publisher discovery requests_per_second must be greater than zero."
            )
        if max_response_bytes < 1024:
            raise ValueError("Publisher discovery response limit is too small.")
        if not 1 <= max_records_per_query <= 100:
            raise ValueError(
                "Publisher discovery record limit must be between 1 and 100."
            )
        self._timeout = timeout
        self._max_retries = max_retries
        self._minimum_interval = 1.0 / requests_per_second
        self._user_agent = user_agent
        self._opener = opener
        self._clock = clock
        self._sleeper = sleeper
        self._max_response_bytes = max_response_bytes
        self._max_records_per_query = max_records_per_query
        self._last_request_at: Optional[float] = None
        self._rate_limit_lock = threading.Lock()
        self._cache: Dict[
            Tuple[str, str, date, date], Tuple[Mapping[str, Any], ...]
        ] = {}

    @classmethod
    def from_environment(cls) -> "PublisherDiscoveryClient":
        return cls(
            timeout=_read_float("PUBLISHER_DISCOVERY_TIMEOUT_SECONDS", 12.0),
            max_retries=_read_int("PUBLISHER_DISCOVERY_MAX_RETRIES", 1),
            requests_per_second=_read_float(
                "PUBLISHER_DISCOVERY_REQUESTS_PER_SECOND", 1.0
            ),
            max_records_per_query=_read_int(
                "PUBLISHER_DISCOVERY_MAX_RECORDS_PER_QUERY", 25
            ),
        )

    def fetch_news(
        self,
        profile: PublisherDiscoveryProfile,
        company_query: str,
        start_date: date,
        end_date: date,
    ) -> List[Mapping[str, Any]]:
        """Search one reviewed publisher and return only verified-source items."""
        cache_key = (profile.source, company_query, start_date, end_date)
        cached = self._cache.get(cache_key)
        if cached is not None:
            return list(cached)
        query = f'"{company_query}" site:{profile.query_domain}'
        parameters = urlencode({
            'q': query,
            'hl': profile.hl,
            'gl': profile.gl,
            'ceid': profile.ceid,
        })
        url = f"{GOOGLE_NEWS_RSS_URL}?{parameters}"
        body = self._get_xml(url, profile.language)
        records = parse_publisher_discovery_rss(
            body,
            start_date=start_date,
            end_date=end_date,
            zone=ZoneInfo(profile.timezone),
            publisher_domains=profile.publisher_domains,
        )
        records.sort(key=lambda row: row["published"], reverse=True)
        records = records[:self._max_records_per_query]
        self._cache[cache_key] = tuple(records)
        return list(records)

    def _get_xml(self, url: str, language: str) -> bytes:
        for attempt in range(self._max_retries + 1):
            self._wait_for_rate_limit()
            request = Request(
                url,
                headers={
                    "User-Agent": self._user_agent,
                    "Accept": "application/rss+xml,application/xml,text/xml,*/*;q=0.5",
                    "Accept-Language": f"{language},en;q=0.5",
                },
                method="GET",
            )
            try:
                with self._opener(request, timeout=self._timeout) as response:
                    response_url = _response_url(response, url)
                    if not _is_allowed_https_url(
                        response_url, GOOGLE_NEWS_DOMAINS
                    ):
                        raise PublisherDiscoveryDataError(
                            "Publisher discovery redirected outside Google News: "
                            f"{response_url}"
                        )
                    declared = _content_length(response)
                    if declared is not None and declared > self._max_response_bytes:
                        raise PublisherDiscoveryDataError(
                            "Publisher discovery response exceeded byte limit."
                        )
                    return _read_limited(
                        response,
                        self._max_response_bytes,
                        GOOGLE_NEWS_RSS_URL,
                    )
            except HTTPError as error:
                if (
                    error.code not in RETRYABLE_STATUS_CODES
                    or attempt == self._max_retries
                ):
                    raise PublisherDiscoveryRequestError(
                        "Publisher discovery failed with HTTP "
                        f"{error.code}: {profile_safe_url(url)}"
                    ) from error
            except (URLError, TimeoutError, OSError) as error:
                if attempt == self._max_retries:
                    raise PublisherDiscoveryRequestError(
                        "Publisher discovery request failed after "
                        f"{self._max_retries + 1} attempts."
                    ) from error
            self._sleeper(0.5 * (2**attempt))
        raise PublisherDiscoveryRequestError("Publisher discovery request failed.")

    def _wait_for_rate_limit(self) -> None:
        with self._rate_limit_lock:
            now = self._clock()
            if self._last_request_at is not None:
                remaining = self._minimum_interval - (now - self._last_request_at)
                if remaining > 0:
                    self._sleeper(remaining)
                    now = self._clock()
            self._last_request_at = now


class RegionalPublisherDiscoveryConnector:
    """Query one publisher per requested company with strict local matching."""

    max_lookback_days = MAX_LOOKBACK_DAYS
    coverage_kind = "bounded_window"
    requires_item_filter = True

    def __init__(
        self,
        profile: PublisherDiscoveryProfile,
        client: Optional[PublisherDiscoveryClient] = None,
        universe: Optional[Mapping[str, Mapping[str, str]]] = None,
    ) -> None:
        self.profile = profile
        self.name = profile.source
        self.provider = profile.publisher
        self._client = client or PublisherDiscoveryClient.from_environment()
        self._universe = dict(
            universe if universe is not None else _identity_map(profile.market)
        )
        self._last_errors: Tuple[Tuple[str, str], ...] = ()

    @property
    def last_errors(self) -> Tuple[Tuple[str, str], ...]:
        return self._last_errors

    def merge_universe(
        self,
        identities: Mapping[str, Mapping[str, str]],
    ) -> None:
        for raw_ticker, raw_identity in identities.items():
            ticker = _normalize_ticker(raw_ticker)
            identity = {
                str(key): str(value)
                for key, value in raw_identity.items()
            }
            if ticker and str(identity.get("name") or "").strip():
                self._universe.setdefault(ticker, identity)

    def collect(self, request: CollectionRequest) -> List[InformationItem]:
        items: List[InformationItem] = []
        failures: List[Tuple[str, str]] = []
        collected_at = datetime.now(timezone.utc)
        for raw_ticker in request.tickers:
            if request.market_for(raw_ticker) != self.profile.market:
                continue
            ticker = _normalize_ticker(raw_ticker)
            identity = _identity_for(self._universe, ticker)
            issuer = str(identity.get("name") or "").strip()
            aliases = _company_aliases(
                identity,
                minimum_trimmed_length=3,
            )
            if not issuer or not aliases:
                failures.append((ticker, f"no_universe_identity: {ticker}"))
                continue
            company_query = aliases[-1]
            try:
                records = self._client.fetch_news(
                    self.profile,
                    company_query,
                    request.start_date,
                    request.end_date,
                )
                for record in records:
                    matched = _matched_aliases(record, aliases)
                    items.append(InformationItem(
                        source=self.profile.source,
                        source_type="news",
                        external_id=f"{ticker}:{record['external_id']}",
                        tickers=(ticker,),
                        issuer=issuer,
                        published_at=record["published"],
                        title=str(record["title"]),
                        document_type="publisher_news_discovery",
                        url=str(record["url"]),
                        collected_at=collected_at,
                        raw_metadata={
                            "provider": "google_news_rss",
                            "discovery_method": "publisher_domain_scoped",
                            "publisher": self.profile.publisher,
                            "publisher_domains": list(
                                self.profile.publisher_domains
                            ),
                            "publisher_source_name": record["publisher_name"],
                            "publisher_source_url": record["publisher_url"],
                            "publisher_link_resolved": False,
                            "query_domain": self.profile.query_domain,
                            "language": self.profile.language,
                            "stock_code": ticker,
                            "matched_aliases": list(matched),
                            "candidate_requires_ai": True,
                            "access_note": self.profile.access_note,
                            "article_body_fetched": False,
                            "source_role": "regional_authoritative_press",
                        },
                        market=self.profile.market,
                        summary=None,
                        effective_at=record["published"],
                    ))
            except Exception as error:
                message = str(error) or error.__class__.__name__
                failures.append((ticker, message))
                LOGGER.warning(
                    "publisher_discovery source=%s ticker=%s "
                    "status=failure error=%s",
                    self.profile.source,
                    ticker,
                    message,
                )
        self._last_errors = tuple(failures)
        if len(request.tickers) == 1 and failures:
            raise PublisherDiscoveryRequestError(failures[0][1])
        return items


def parse_publisher_discovery_rss(
    body: bytes,
    *,
    start_date: date,
    end_date: date,
    zone: ZoneInfo,
    publisher_domains: Tuple[str, ...],
) -> List[Mapping[str, Any]]:
    """Parse Google News RSS and drop results not attributed to the publisher."""
    try:
        root = ElementTree.fromstring(body)
    except (ElementTree.ParseError, ValueError) as error:
        raise PublisherDiscoveryDataError(
            "Publisher discovery response is not valid XML."
        ) from error
    if _local_name(root.tag).lower() != "rss":
        raise PublisherDiscoveryDataError(
            "Publisher discovery response is not RSS."
        )
    records: List[Mapping[str, Any]] = []
    for item in root.iter():
        if _local_name(item.tag).lower() != "item":
            continue
        title = _clean_text(_child_text(item, "title"))
        url = _clean_text(_child_text(item, "link"))
        published = _parse_datetime(_child_text(item, "pubDate"), zone)
        publisher_element = _child(item, "source")
        publisher_name = _clean_text(
            str(getattr(publisher_element, "text", "") or "")
        )
        publisher_url = str(
            publisher_element.get("url")
            if publisher_element is not None
            else ""
        ).strip()
        if not title or published is None:
            continue
        if not _is_allowed_https_url(url, GOOGLE_NEWS_DOMAINS):
            continue
        if not _is_allowed_https_url(publisher_url, publisher_domains):
            continue
        if not start_date <= published.astimezone(zone).date() <= end_date:
            continue
        guid = _clean_text(_child_text(item, "guid"))
        records.append({
            "external_id": guid or hashlib.sha256(url.encode("utf-8")).hexdigest(),
            "title": title,
            "url": url,
            "published": published.astimezone(timezone.utc),
            "summary": None,
            "publisher_name": publisher_name,
            "publisher_url": publisher_url,
        })
    return records


def _child(element: Any, name: str) -> Optional[Any]:
    for child in element:
        if _local_name(child.tag).lower() == name.lower():
            return child
    return None


def _child_text(element: Any, name: str) -> str:
    child = _child(element, name)
    return str(getattr(child, "text", "") or "")


def _local_name(tag: object) -> str:
    return str(tag).split("}")[-1]


def _parse_datetime(value: str, default_zone: ZoneInfo) -> Optional[datetime]:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        parsed = parsedate_to_datetime(text)
    except (TypeError, ValueError, OverflowError):
        try:
            parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError:
            return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=default_zone)
    return parsed


def _clean_text(value: str) -> str:
    text = html.unescape(re.sub(r"<[^>]+>", " ", str(value or "")))
    return re.sub(r"\s+", " ", text).strip()


def profile_safe_url(url: str) -> str:
    """Avoid logging company queries while retaining the stable endpoint."""
    return str(url).split("?", 1)[0]
