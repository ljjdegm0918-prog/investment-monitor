"""Yahoo Finance UK stock news RSS client.

Recon (verified live): ``GET https://feeds.finance.yahoo.com/rss/2.0/headline
?s=VOD.L&region=GB&lang=en-GB`` returns an RSS 2.0 feed with real Yahoo
article links and RFC822 pub dates. Symbols need the ``.L`` suffix at request
time only. This is a key-free public RSS mirror; the feed may change without
notice, so parse failures raise a data error instead of fake success.
"""

from __future__ import annotations

import hashlib
import html
import logging
import os
import re
import threading
import time
from datetime import date, datetime
from email.utils import parsedate_to_datetime
from typing import Any, Callable, List, Mapping, Optional
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
import xml.etree.ElementTree as ElementTree

LOGGER = logging.getLogger(__name__)

DEFAULT_BASE_URL = "https://feeds.finance.yahoo.com/rss/2.0/headline"
RETRYABLE_STATUS_CODES = frozenset({429, 500, 502, 503, 504})


class YahooNewsError(Exception):
    """Base error for Yahoo Finance UK news collection."""


class YahooNewsRequestError(YahooNewsError):
    """Raised when the Yahoo request cannot be completed."""


class YahooNewsDataError(YahooNewsError):
    """Raised when Yahoo returns an unexpected feed."""


class YahooNewsClient:
    """Small stdlib RSS client for Yahoo Finance UK stock news."""

    def __init__(
        self,
        base_url: str = DEFAULT_BASE_URL,
        timeout: float = 20.0,
        max_retries: int = 1,
        requests_per_second: float = 1.0,
        user_agent: str = "InvestmentMonitor/0.1 (internal workspace)",
        opener: Callable[..., Any] = urlopen,
        clock: Callable[[], float] = time.monotonic,
        sleeper: Callable[[float], None] = time.sleep,
    ) -> None:
        if not base_url.strip():
            raise ValueError("Yahoo news base URL must not be empty.")
        if timeout <= 0:
            raise ValueError("Yahoo news timeout must be greater than zero.")
        if max_retries < 0:
            raise ValueError("Yahoo news max_retries must not be negative.")
        if requests_per_second <= 0:
            raise ValueError(
                "Yahoo news requests_per_second must be greater than zero."
            )
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout
        self._max_retries = max_retries
        self._minimum_interval = 1.0 / requests_per_second
        self._user_agent = user_agent
        self._opener = opener
        self._clock = clock
        self._sleeper = sleeper
        self._last_request_at: Optional[float] = None
        self._rate_limit_lock = threading.Lock()

    @classmethod
    def from_environment(cls) -> "YahooNewsClient":
        return cls(
            base_url=os.environ.get("YAHOO_UK_NEWS_URL", DEFAULT_BASE_URL),
            timeout=_read_float_environment("YAHOO_UK_NEWS_TIMEOUT_SECONDS", 20.0),
            max_retries=_read_int_environment("YAHOO_UK_NEWS_MAX_RETRIES", 1),
            requests_per_second=_read_float_environment(
                "YAHOO_UK_NEWS_REQUESTS_PER_SECOND",
                1.0,
            ),
        )

    def fetch_news(
        self,
        symbol: str,
        start_date: date,
        end_date: date,
    ) -> List[Mapping[str, Any]]:
        """Fetch and parse stock news for a Yahoo UK symbol (e.g. VOD.L)."""
        url = (
            f"{self._base_url}?s={_quote(symbol)}&region=GB&lang=en-GB"
        )
        body = self._get_xml(url)
        return _parse_rss(
            body,
            start_date=start_date,
            end_date=end_date,
        )

    def _get_xml(self, url: str) -> bytes:
        for attempt in range(self._max_retries + 1):
            self._wait_for_rate_limit()
            request = Request(
                url,
                headers={
                    "User-Agent": self._user_agent,
                    "Accept-Language": "en-GB,en;q=0.9",
                    "Accept": "application/rss+xml,application/xml,*/*;q=0.8",
                },
                method="GET",
            )
            try:
                with self._opener(request, timeout=self._timeout) as response:
                    return response.read()
            except HTTPError as error:
                if (
                    error.code not in RETRYABLE_STATUS_CODES
                    or attempt == self._max_retries
                ):
                    raise YahooNewsRequestError(
                        f"Yahoo news request failed with HTTP "
                        f"{error.code}: {url}"
                    ) from error
            except URLError as error:
                if attempt == self._max_retries:
                    raise YahooNewsRequestError(
                        f"Yahoo news request failed after "
                        f"{self._max_retries + 1} attempts: {url}"
                    ) from error
            except TimeoutError as error:
                if attempt == self._max_retries:
                    raise YahooNewsRequestError(
                        f"Yahoo news request timed out after "
                        f"{self._max_retries + 1} attempts: {url}"
                    ) from error
            self._sleeper(0.5 * (2**attempt))
        raise YahooNewsRequestError(f"Yahoo news request failed: {url}")

    def _wait_for_rate_limit(self) -> None:
        with self._rate_limit_lock:
            now = self._clock()
            if self._last_request_at is not None:
                remaining = (
                    self._minimum_interval - (now - self._last_request_at)
                )
                if remaining > 0:
                    self._sleeper(remaining)
                    now = self._clock()
            self._last_request_at = now


def _parse_rss(
    body: bytes,
    *,
    start_date: date,
    end_date: date,
) -> List[Mapping[str, Any]]:
    try:
        root = ElementTree.fromstring(body)
    except ElementTree.ParseError as error:
        raise YahooNewsDataError(
            "Yahoo news response is not valid XML."
        ) from error
    if str(root.tag).split("}")[-1].lower() != "rss":
        raise YahooNewsDataError(
            "Yahoo news response is not an RSS feed."
        )
    records: List[Mapping[str, Any]] = []
    for item in root.iter():
        if str(item.tag).split("}")[-1].lower() != "item":
            continue
        title = _child_text(item, "title")
        link = _child_text(item, "link")
        if not title or not link:
            continue
        published = _parse_rfc822(_child_text(item, "pubDate"))
        if published is None:
            continue
        if not start_date <= published.date() <= end_date:
            continue
        description = _child_text(item, "description")
        records.append(
            {
                "external_id": _article_id(link),
                "title": html.unescape(title).strip(),
                "url": link,
                "published": published,
                "summary": _clean_description(description),
            }
        )
    return records


def _child_text(element: Any, local_name: str) -> str:
    for child in element:
        if str(child.tag).split("}")[-1].lower() == local_name.lower():
            return child.text or ""
    return ""


def _parse_rfc822(value: str) -> Optional[datetime]:
    try:
        parsed = parsedate_to_datetime(value.strip())
    except (TypeError, ValueError):
        return None
    return parsed


def _article_id(url: str) -> str:
    match = re.search(r"[-/](\d{6,})\.html", url)
    if match is not None:
        return match.group(1)
    return hashlib.sha1(url.encode("utf-8")).hexdigest()


def _clean_description(value: str) -> Optional[str]:
    if not value:
        return None
    text = html.unescape(re.sub(r"<[^>]+>", " ", value))
    text = re.sub(r"\s+", " ", text).strip()
    return text or None


def _quote(symbol: str) -> str:
    from urllib.parse import quote

    return quote(symbol)


def _read_float_environment(name: str, default: float) -> float:
    value = os.environ.get(name)
    if value is None:
        return default
    try:
        return float(value)
    except ValueError as error:
        raise ValueError(f"{name} must be a number.") from error


def _read_int_environment(name: str, default: int) -> int:
    value = os.environ.get(name)
    if value is None:
        return default
    try:
        return int(value)
    except ValueError as error:
        raise ValueError(f"{name} must be an integer.") from error
