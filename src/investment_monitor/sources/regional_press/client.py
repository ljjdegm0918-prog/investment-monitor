"""Bounded RSS client for reviewed regional publisher feeds."""

from __future__ import annotations

import hashlib
import html
import os
import re
import threading
import time
from datetime import date, datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Any, Callable, Dict, List, Mapping, Optional, Tuple
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen
import xml.etree.ElementTree as ElementTree
from zoneinfo import ZoneInfo

from .profiles import RegionalPressProfile

MAX_RESPONSE_BYTES = 4 * 1024 * 1024
RETRYABLE_STATUS_CODES = frozenset({429, 500, 502, 503, 504})


class RegionalPressError(Exception):
    """Base error for direct regional publisher feeds."""


class RegionalPressRequestError(RegionalPressError):
    """Raised when a publisher feed request cannot be completed."""


class RegionalPressDataError(RegionalPressError):
    """Raised when a publisher returns malformed or unsupported feed data."""


class RegionalPressClient:
    """Fetch publisher-owned RSS and expose only feed metadata."""

    def __init__(
        self,
        timeout: float = 15.0,
        max_retries: int = 1,
        requests_per_second: float = 1.0,
        user_agent: str = "InvestmentMonitor/0.1 regional-news",
        opener: Callable[..., Any] = urlopen,
        clock: Callable[[], float] = time.monotonic,
        sleeper: Callable[[float], None] = time.sleep,
        max_response_bytes: int = MAX_RESPONSE_BYTES,
    ) -> None:
        if timeout <= 0:
            raise ValueError("Regional press timeout must be greater than zero.")
        if max_retries < 0:
            raise ValueError("Regional press max_retries must not be negative.")
        if requests_per_second <= 0:
            raise ValueError(
                "Regional press requests_per_second must be greater than zero."
            )
        if max_response_bytes < 1024:
            raise ValueError("Regional press response limit is too small.")
        self._timeout = timeout
        self._max_retries = max_retries
        self._minimum_interval = 1.0 / requests_per_second
        self._user_agent = user_agent
        self._opener = opener
        self._clock = clock
        self._sleeper = sleeper
        self._max_response_bytes = max_response_bytes
        self._last_request_at: Optional[float] = None
        self._rate_limit_lock = threading.Lock()
        self._cache: Dict[
            Tuple[str, date, date], Tuple[Mapping[str, Any], ...]
        ] = {}

    @classmethod
    def from_environment(cls) -> "RegionalPressClient":
        return cls(
            timeout=_read_float("REGIONAL_PRESS_TIMEOUT_SECONDS", 15.0),
            max_retries=_read_int("REGIONAL_PRESS_MAX_RETRIES", 1),
            requests_per_second=_read_float(
                "REGIONAL_PRESS_REQUESTS_PER_SECOND", 1.0
            ),
        )

    def fetch_news(
        self,
        profile: RegionalPressProfile,
        start_date: date,
        end_date: date,
    ) -> List[Mapping[str, Any]]:
        """Fetch once per profile/range and combine its reviewed feed URLs."""
        cache_key = (profile.source, start_date, end_date)
        cached = self._cache.get(cache_key)
        if cached is not None:
            return list(cached)
        records: List[Mapping[str, Any]] = []
        seen = set()
        for feed_url in profile.feed_urls:
            allowed_feed_domains = _allowed_feed_domains(profile, feed_url)
            if not _is_allowed_https_url(feed_url, allowed_feed_domains):
                raise RegionalPressDataError(
                    f"Regional publisher feed URL is not approved HTTPS: {feed_url}"
                )
            body = self._get_xml(
                feed_url,
                profile.language,
                allowed_domains=allowed_feed_domains,
            )
            for record in parse_regional_rss(
                body,
                feed_url=feed_url,
                start_date=start_date,
                end_date=end_date,
                zone=ZoneInfo(profile.timezone),
            ):
                article_domains = (
                    profile.publisher_domain,
                    *profile.article_domains,
                )
                if not _is_allowed_https_url(
                    str(record["url"]), article_domains
                ):
                    raise RegionalPressDataError(
                        "Regional publisher item URL is outside the approved "
                        f"publisher domains: {record['url']}"
                    )
                key = str(record["url"])
                if key in seen:
                    continue
                seen.add(key)
                records.append(record)
        records.sort(key=lambda row: row["published"], reverse=True)
        self._cache[cache_key] = tuple(records)
        return list(records)

    def _get_xml(
        self,
        url: str,
        language: str,
        *,
        allowed_domains: Tuple[str, ...],
    ) -> bytes:
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
                        response_url, allowed_domains
                    ):
                        raise RegionalPressDataError(
                            "Regional publisher feed redirected outside the "
                            f"approved domains: {response_url}"
                        )
                    declared = _content_length(response)
                    if declared is not None and declared > self._max_response_bytes:
                        raise RegionalPressDataError(
                            f"Regional press response exceeded byte limit: {url}"
                        )
                    return _read_limited(response, self._max_response_bytes, url)
            except HTTPError as error:
                if (
                    error.code not in RETRYABLE_STATUS_CODES
                    or attempt == self._max_retries
                ):
                    raise RegionalPressRequestError(
                        f"Regional press request failed with HTTP {error.code}: {url}"
                    ) from error
            except (URLError, TimeoutError, OSError) as error:
                if attempt == self._max_retries:
                    raise RegionalPressRequestError(
                        f"Regional press request failed after "
                        f"{self._max_retries + 1} attempts: {url}"
                    ) from error
            self._sleeper(0.5 * (2**attempt))
        raise RegionalPressRequestError(f"Regional press request failed: {url}")

    def _wait_for_rate_limit(self) -> None:
        with self._rate_limit_lock:
            now = self._clock()
            if self._last_request_at is not None:
                remaining = self._minimum_interval - (now - self._last_request_at)
                if remaining > 0:
                    self._sleeper(remaining)
                    now = self._clock()
            self._last_request_at = now


def parse_regional_rss(
    body: bytes,
    *,
    feed_url: str,
    start_date: date,
    end_date: date,
    zone: ZoneInfo,
) -> List[Mapping[str, Any]]:
    """Parse RSS 2.0 metadata without retaining full article bodies."""
    try:
        root = ElementTree.fromstring(body)
    except (ElementTree.ParseError, ValueError) as error:
        raise RegionalPressDataError(
            f"Regional publisher response is not valid XML: {feed_url}"
        ) from error
    if _local_name(root.tag).lower() != "rss":
        raise RegionalPressDataError(
            f"Regional publisher response is not RSS 2.0: {feed_url}"
        )
    records: List[Mapping[str, Any]] = []
    for item in root.iter():
        if _local_name(item.tag).lower() != "item":
            continue
        title = _clean_text(_child_text(item, "title"))
        url = _clean_text(_child_text(item, "link"))
        published = _parse_datetime(
            _child_text(item, "pubDate")
            or _child_text(item, "date")
            or _child_text(item, "published"),
            default_zone=zone,
        )
        if not title or published is None:
            continue
        if not _is_https_url(url):
            raise RegionalPressDataError(
                f"Regional publisher item URL is not HTTPS: {url or '<empty>'}"
            )
        if not start_date <= published.astimezone(zone).date() <= end_date:
            continue
        summary = _clean_summary(_child_text(item, "description"))
        guid = _clean_text(_child_text(item, "guid"))
        records.append(
            {
                "external_id": guid or hashlib.sha256(url.encode("utf-8")).hexdigest(),
                "title": title,
                "url": url,
                "published": published.astimezone(timezone.utc),
                "summary": summary,
                "feed_url": feed_url,
            }
        )
    return records


def _child_text(element: Any, name: str) -> str:
    for child in element:
        if _local_name(child.tag).lower() == name.lower():
            value = child.text or ""
            if value.strip():
                return value
    return ""


def _local_name(tag: object) -> str:
    return str(tag).split("}")[-1]


def _parse_datetime(
    value: str,
    *,
    default_zone: ZoneInfo,
) -> Optional[datetime]:
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


def _clean_summary(value: str) -> Optional[str]:
    text = _clean_text(value)
    if not text:
        return None
    return text[:2000]


def _is_https_url(value: str) -> bool:
    parsed = urlsplit(str(value or ""))
    return parsed.scheme.lower() == "https" and bool(parsed.hostname)


def _is_allowed_https_url(value: str, domains: Tuple[str, ...]) -> bool:
    if not _is_https_url(value):
        return False
    hostname = str(urlsplit(value).hostname or "").rstrip(".").lower()
    for raw_domain in domains:
        domain = str(raw_domain or "").rstrip(".").lower()
        if domain and (hostname == domain or hostname.endswith(f".{domain}")):
            return True
    return False


def _allowed_feed_domains(
    profile: RegionalPressProfile,
    feed_url: str,
) -> Tuple[str, ...]:
    feed_host = str(urlsplit(feed_url).hostname or "").lower()
    return tuple(
        domain
        for domain in (profile.publisher_domain, feed_host)
        if domain
    )


def _response_url(response: Any, requested_url: str) -> str:
    getter = getattr(response, "geturl", None)
    if not callable(getter):
        return requested_url
    return str(getter() or requested_url)


def _content_length(response: Any) -> Optional[int]:
    headers = getattr(response, "headers", None)
    if headers is None or not hasattr(headers, "get"):
        return None
    value = headers.get("Content-Length")
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _read_limited(response: Any, limit: int, url: str) -> bytes:
    chunks = []
    total = 0
    while True:
        try:
            chunk = response.read(64 * 1024)
        except TypeError:
            chunk = response.read()
        if not chunk:
            break
        total += len(chunk)
        if total > limit:
            raise RegionalPressDataError(
                f"Regional press response exceeded byte limit: {url}"
            )
        chunks.append(chunk)
    return b"".join(chunks)


def _read_float(name: str, default: float) -> float:
    value = os.environ.get(name)
    try:
        return float(value) if value is not None else default
    except ValueError as error:
        raise ValueError(f"{name} must be a number.") from error


def _read_int(name: str, default: int) -> int:
    value = os.environ.get(name)
    try:
        return int(value) if value is not None else default
    except ValueError as error:
        raise ValueError(f"{name} must be an integer.") from error
