"""EQS News (ex-DGAP) key-free JSON client for Italian issuer disclosures.

Recon (verified live 2026-08-10):
``GET https://www.eqs-news.com/wp-json/eqsnews/v1/news?isin=IT0005239360``
returns JSON ``{status, records:[...]}`` with headline, categoryCode,
dateUtc, companyName and isin — no API key. Coverage of Italian ISINs is
partial (UniCredit returns records; ENI/Intesa return empty lists), which
is honest rather than a failure. This is the same unofficial public
WordPress JSON surface as the DE/NL EQS connectors and may change without
notice; it is NOT a Consob official feed.
"""

from __future__ import annotations

import json
import logging
import os
import re
import threading
import time
from datetime import date, datetime, timezone
from typing import Any, Callable, List, Mapping, Optional
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

LOGGER = logging.getLogger(__name__)

ROME = ZoneInfo("Europe/Rome")
DEFAULT_BASE_URL = "https://www.eqs-news.com/wp-json/eqsnews/v1"
DEFAULT_PUBLIC_BASE = "https://www.eqs-news.com"
RETRYABLE_STATUS_CODES = frozenset({429, 500, 502, 503, 504})
_SLUG_RE = re.compile(r"[^a-z0-9]+")


class EqsItError(Exception):
    """Base error for EQS News IT collection."""


class EqsItRequestError(EqsItError):
    """Raised when the EQS request cannot be completed."""


class EqsItDataError(EqsItError):
    """Raised when EQS returns unexpected JSON."""


class EqsItClient:
    """Small stdlib JSON client for EQS News Italian issuer disclosures."""

    def __init__(
        self,
        base_url: str = DEFAULT_BASE_URL,
        public_base: str = DEFAULT_PUBLIC_BASE,
        timeout: float = 20.0,
        max_retries: int = 1,
        requests_per_second: float = 1.0,
        user_agent: str = "InvestmentMonitor/0.1 (internal workspace)",
        opener: Callable[..., Any] = urlopen,
        clock: Callable[[], float] = time.monotonic,
        sleeper: Callable[[float], None] = time.sleep,
    ) -> None:
        if not base_url.strip():
            raise ValueError("EQS IT base URL must not be empty.")
        if timeout <= 0:
            raise ValueError("EQS IT timeout must be greater than zero.")
        if max_retries < 0:
            raise ValueError("EQS IT max_retries must not be negative.")
        if requests_per_second <= 0:
            raise ValueError(
                "EQS IT requests_per_second must be greater than zero."
            )
        self._base_url = base_url.rstrip("/")
        self._public_base = public_base.rstrip("/")
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
    def from_environment(cls) -> "EqsItClient":
        return cls(
            base_url=os.environ.get("EQS_IT_URL", DEFAULT_BASE_URL),
            public_base=os.environ.get(
                "EQS_IT_PUBLIC_BASE", DEFAULT_PUBLIC_BASE
            ),
            timeout=_env_float("EQS_IT_TIMEOUT_SECONDS", 20.0),
            max_retries=_env_int("EQS_IT_MAX_RETRIES", 1),
            requests_per_second=_env_float(
                "EQS_IT_REQUESTS_PER_SECOND", 1.0
            ),
        )

    def fetch_by_isin(
        self,
        isin: str,
        start_date: date,
        end_date: date,
        *,
        max_pages: int = 5,
    ) -> List[Mapping[str, Any]]:
        """Fetch EQS news records for an ISIN and filter to the Rome day window."""
        code = str(isin or "").strip().upper()
        if not code:
            raise ValueError("ISIN must not be empty.")
        records: List[Mapping[str, Any]] = []
        for page in range(1, max_pages + 1):
            url = (
                f"{self._base_url}/news?isin={quote(code)}"
                f"&page={page}"
            )
            payload = self._get_json(url)
            page_records = payload.get("records")
            if not isinstance(page_records, list) or not page_records:
                break
            for raw in page_records:
                parsed = self._parse_record(raw)
                if parsed is None:
                    continue
                day = rome_day(parsed["published_at"])
                if day < start_date or day > end_date:
                    continue
                records.append(parsed)
            if len(page_records) < 10:
                break
        return records

    def _parse_record(
        self, raw: Mapping[str, Any]
    ) -> Optional[Mapping[str, Any]]:
        if not isinstance(raw, Mapping):
            return None
        external_id = str(raw.get("id") or "").strip()
        headline = str(raw.get("headline") or "").strip()
        if not external_id or not headline:
            return None
        published = _parse_eqs_datetime(
            str(raw.get("dateUtc") or raw.get("date") or "")
        )
        if published is None:
            return None
        category = str(raw.get("category") or "EQS News").strip()
        url = (
            f"{self._public_base}/news/"
            f"{_slug(category)}/{_slug(headline)}/{external_id}"
        )
        bare_id = external_id.rsplit("_", 1)[0]
        return {
            "external_id": bare_id,
            "title": headline,
            "published_at": published,
            "url": url,
            "category": category,
            "category_code": str(raw.get("categoryCode") or ""),
            "company_name": str(raw.get("companyName") or ""),
            "isin": str(raw.get("isin") or "").upper(),
            "locale_id": external_id,
        }

    def _get_json(self, url: str) -> Mapping[str, Any]:
        body = self._get_bytes(url)
        try:
            payload = json.loads(body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise EqsItDataError(
                f"EQS IT returned non-JSON payload for {url}"
            ) from error
        if not isinstance(payload, Mapping):
            raise EqsItDataError(
                f"EQS IT JSON root must be an object for {url}"
            )
        return payload

    def _get_bytes(self, url: str) -> bytes:
        for attempt in range(self._max_retries + 1):
            self._wait_for_rate_limit()
            request = Request(
                url,
                headers={
                    "User-Agent": self._user_agent,
                    "Accept": "application/json",
                    "Referer": f"{self._public_base}/",
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
                    raise EqsItRequestError(
                        f"EQS IT request failed with HTTP "
                        f"{error.code}: {url}"
                    ) from error
            except URLError as error:
                if attempt == self._max_retries:
                    raise EqsItRequestError(
                        f"EQS IT request failed after "
                        f"{self._max_retries + 1} attempts: {url}"
                    ) from error
            except TimeoutError as error:
                if attempt == self._max_retries:
                    raise EqsItRequestError(
                        f"EQS IT request timed out after "
                        f"{self._max_retries + 1} attempts: {url}"
                    ) from error
            self._sleeper(0.5 * (2**attempt))
        raise EqsItRequestError(f"EQS IT request failed: {url}")

    def _wait_for_rate_limit(self) -> None:
        with self._rate_limit_lock:
            now = self._clock()
            if self._last_request_at is not None:
                remaining = self._minimum_interval - (
                    now - self._last_request_at
                )
                if remaining > 0:
                    self._sleeper(remaining)
                    now = self._clock()
            self._last_request_at = now


def rome_day(value: datetime) -> date:
    """Calendar day in Europe/Rome for an aware/naive UTC datetime."""
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(ROME).date()


def _slug(value: str) -> str:
    text = _SLUG_RE.sub("-", str(value or "").casefold()).strip("-")
    return text or "news"


def _parse_eqs_datetime(value: str) -> Optional[datetime]:
    text = str(value or "").strip()
    if not text:
        return None
    for fmt in (
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%dT%H:%M:%S%z",
        "%Y-%m-%dT%H:%M:%S",
    ):
        try:
            if fmt.endswith("%z"):
                normalized = text.replace("Z", "+0000")
                if len(normalized) >= 5 and normalized[-3] == ":":
                    normalized = normalized[:-3] + normalized[-2:]
                parsed = datetime.strptime(normalized, fmt)
            else:
                parsed = datetime.strptime(
                    text[:19], "%Y-%m-%d %H:%M:%S"
                )
            if parsed.tzinfo is None:
                return parsed.replace(tzinfo=timezone.utc)
            return parsed.astimezone(timezone.utc)
        except ValueError:
            continue
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _env_float(name: str, default: float) -> float:
    value = os.environ.get(name)
    if value is None:
        return default
    try:
        return float(value)
    except ValueError as error:
        raise ValueError(f"{name} must be a number.") from error


def _env_int(name: str, default: int) -> int:
    value = os.environ.get(name)
    if value is None:
        return default
    try:
        return int(value)
    except ValueError as error:
        raise ValueError(f"{name} must be an integer.") from error
