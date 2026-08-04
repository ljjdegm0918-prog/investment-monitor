"""Finnhub company-news connector for the production News source.

Finnhub (https://finnhub.io) provides an official JSON API with a free tier
and documented rate limits. Company news is fetched per symbol with
``GET /api/v1/company-news``, which is appropriate for an internal
investment-monitoring workspace.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import threading
import time
from datetime import date, datetime, timezone
from typing import Any, Callable, Dict, List, Mapping, Optional, Sequence, Tuple
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from ...connectors.base import ConnectorUnavailableError
from ...models import (
    CollectionRequest,
    InformationItem,
    MARKET_CN,
    MARKET_HK,
)

LOGGER = logging.getLogger(__name__)

DEFAULT_BASE_URL = "https://finnhub.io/api/v1"
MAX_LOOKBACK_DAYS = 30
RETRYABLE_STATUS_CODES = frozenset({429, 500, 502, 503, 504})
NO_COVERAGE_STATUS_CODES = frozenset({400, 404})


class FinnhubNewsError(Exception):
    """Base error for Finnhub news collection."""


class FinnhubNewsRequestError(FinnhubNewsError):
    """Raised when a Finnhub HTTP request cannot be completed."""

    def __init__(self, message: str, status_code: Optional[int] = None) -> None:
        super().__init__(message)
        self.status_code = status_code


class FinnhubNewsDataError(FinnhubNewsError):
    """Raised when Finnhub returns data in an unexpected format."""


class FinnhubClient:
    """Small JSON HTTP client with timeout, retries, and rate limiting."""

    def __init__(
        self,
        api_key: str,
        base_url: str = DEFAULT_BASE_URL,
        timeout: float = 10.0,
        max_retries: int = 2,
        requests_per_second: float = 1.0,
        opener: Callable[..., Any] = urlopen,
        clock: Callable[[], float] = time.monotonic,
        sleeper: Callable[[float], None] = time.sleep,
    ) -> None:
        if not api_key.strip():
            raise ConnectorUnavailableError(
                "FINNHUB_API_KEY is not configured; News is not connected."
            )
        if not base_url.strip():
            raise ValueError("Finnhub base URL must not be empty.")
        if timeout <= 0:
            raise ValueError("Finnhub timeout must be greater than zero.")
        if max_retries < 0:
            raise ValueError("Finnhub max_retries must not be negative.")
        if requests_per_second <= 0:
            raise ValueError(
                "Finnhub requests_per_second must be greater than zero."
            )
        self._api_key = api_key
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout
        self._max_retries = max_retries
        self._minimum_interval = 1.0 / requests_per_second
        self._opener = opener
        self._clock = clock
        self._sleeper = sleeper
        self._last_request_at: Optional[float] = None
        self._rate_limit_lock = threading.Lock()

    @classmethod
    def from_environment(cls) -> "FinnhubClient":
        """Build a client from environment configuration."""
        api_key = os.environ.get("FINNHUB_API_KEY", "").strip()
        if not api_key:
            raise ConnectorUnavailableError(
                "FINNHUB_API_KEY is not configured; News is not connected."
            )
        return cls(
            api_key=api_key,
            base_url=os.environ.get(
                "FINNHUB_BASE_URL",
                DEFAULT_BASE_URL,
            ),
            timeout=_read_float_environment("FINNHUB_TIMEOUT_SECONDS", 10.0),
            max_retries=_read_int_environment("FINNHUB_MAX_RETRIES", 2),
            requests_per_second=_read_float_environment(
                "FINNHUB_REQUESTS_PER_SECOND",
                1.0,
            ),
        )

    def get_json(
        self,
        path: str,
        parameters: Mapping[str, str],
    ) -> Any:
        """GET one Finnhub endpoint and decode its JSON response."""
        query = urlencode({**dict(parameters), "token": self._api_key})
        url = f"{self._base_url}/{path.lstrip('/')}?{query}"
        for attempt in range(self._max_retries + 1):
            self._wait_for_rate_limit()
            request = Request(
                url,
                headers={"Accept": "application/json"},
                method="GET",
            )
            try:
                with self._opener(request, timeout=self._timeout) as response:
                    body = response.read()
                try:
                    return json.loads(body.decode("utf-8"))
                except (UnicodeDecodeError, json.JSONDecodeError) as error:
                    raise FinnhubNewsDataError(
                        f"Finnhub returned invalid JSON for {url}"
                    ) from error
            except HTTPError as error:
                if (
                    error.code not in RETRYABLE_STATUS_CODES
                    or attempt == self._max_retries
                ):
                    raise FinnhubNewsRequestError(
                        f"Finnhub request failed with HTTP {error.code}: {url}",
                        status_code=error.code,
                    ) from error
            except URLError as error:
                if attempt == self._max_retries:
                    raise FinnhubNewsRequestError(
                        f"Finnhub request failed after "
                        f"{self._max_retries + 1} attempts: {url}"
                    ) from error
            except TimeoutError as error:
                if attempt == self._max_retries:
                    raise FinnhubNewsRequestError(
                        f"Finnhub request timed out after "
                        f"{self._max_retries + 1} attempts: {url}"
                    ) from error
            self._sleeper(0.5 * (2**attempt))
        raise FinnhubNewsRequestError(f"Finnhub request failed: {url}")

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


class FinnhubNewsConnector:
    """Collect real company news for active (ticker, market) companies."""

    name = "news"
    provider = "Finnhub News"
    max_lookback_days = MAX_LOOKBACK_DAYS

    def __init__(self, client: Optional[FinnhubClient] = None) -> None:
        self._client = client or FinnhubClient.from_environment()
        self._last_errors: Tuple[Tuple[str, str], ...] = ()

    @classmethod
    def configuration_error(cls) -> Optional[str]:
        """Return a human-readable reason when the source cannot be enabled."""
        if not os.environ.get("FINNHUB_API_KEY", "").strip():
            return (
                "FINNHUB_API_KEY is not configured; News is not connected."
            )
        return None

    @classmethod
    def from_environment(cls) -> "FinnhubNewsConnector":
        """Build a production connector from environment configuration."""
        configuration_error = cls.configuration_error()
        if configuration_error is not None:
            raise ConnectorUnavailableError(configuration_error)
        return cls(client=FinnhubClient.from_environment())

    @property
    def last_errors(self) -> Tuple[Tuple[str, str], ...]:
        """(ticker, message) pairs from the most recent collect call."""
        return self._last_errors

    def collect(self, request: CollectionRequest) -> List[InformationItem]:
        """Collect news per ticker, allowing partial success per source."""
        items: List[InformationItem] = []
        failures: List[Tuple[str, str]] = []
        collected_at = datetime.now(timezone.utc)

        for ticker in request.tickers:
            market = request.market_for(ticker)
            symbols = _symbols_for(market, ticker)
            ticker_items: List[InformationItem] = []
            candidate_failures: List[str] = []
            for symbol in symbols:
                try:
                    payload = self._client.get_json(
                        "company-news",
                        {
                            "symbol": symbol,
                            "from": request.start_date.isoformat(),
                            "to": request.end_date.isoformat(),
                        },
                    )
                    ticker_items.extend(
                        self._map_articles(
                            payload,
                            ticker=ticker,
                            market=market,
                            symbol=symbol,
                            start_date=request.start_date,
                            end_date=request.end_date,
                            collected_at=collected_at,
                        )
                    )
                except FinnhubNewsRequestError as error:
                    if (
                        error.status_code in NO_COVERAGE_STATUS_CODES
                        and market in (MARKET_HK, MARKET_CN)
                    ):
                        LOGGER.info(
                            "news symbol=%s market=%s no_coverage http=%s",
                            symbol,
                            market,
                            error.status_code,
                        )
                        continue
                    candidate_failures.append(f"{symbol}: {error}")
                except Exception as error:
                    candidate_failures.append(
                        f"{symbol}: {str(error) or error.__class__.__name__}"
                    )

            if ticker_items:
                items.extend(_dedupe_articles(ticker_items))
                if candidate_failures:
                    LOGGER.warning(
                        "news ticker=%s partial_failures=%s",
                        ticker,
                        "; ".join(candidate_failures),
                    )
            elif candidate_failures:
                message = "; ".join(candidate_failures)
                failures.append((ticker, message))
                LOGGER.warning("news ticker=%s status=failure error=%s", ticker, message)

        self._last_errors = tuple(failures)
        if len(request.tickers) == 1 and failures:
            raise FinnhubNewsRequestError(failures[0][1])
        return items

    def _map_articles(
        self,
        payload: Any,
        *,
        ticker: str,
        market: str,
        symbol: str,
        start_date: date,
        end_date: date,
        collected_at: datetime,
    ) -> List[InformationItem]:
        if not isinstance(payload, list):
            raise FinnhubNewsDataError(
                "Finnhub company-news response must be a JSON array."
            )
        items: List[InformationItem] = []
        for article in payload:
            if not isinstance(article, dict):
                continue
            title = str(article.get("headline") or "").strip()
            url = str(article.get("url") or "").strip()
            if not title or not url:
                continue
            raw_id = article.get("id")
            if raw_id is None:
                raw_id = hashlib.sha1(
                    url.encode("utf-8")
                ).hexdigest()
            external_id = str(raw_id)
            published_at = _parse_unix_datetime(article.get("datetime"))
            if published_at is None:
                continue
            if not start_date <= published_at.date() <= end_date:
                continue
            summary = article.get("summary")
            items.append(
                InformationItem(
                    source=self.name,
                    source_type="news",
                    external_id=external_id,
                    tickers=(ticker,),
                    issuer=ticker,
                    published_at=published_at,
                    title=title,
                    document_type="news",
                    url=url,
                    collected_at=collected_at,
                    raw_metadata={
                        "provider": "finnhub",
                        "symbol": symbol,
                        "category": (
                            str(article.get("category") or "")
                            if article.get("category")
                            else None
                        ),
                        "source": (
                            str(article.get("source") or "")
                            if article.get("source")
                            else None
                        ),
                        "image": (
                            str(article.get("image") or "")
                            if article.get("image")
                            else None
                        ),
                        "related": (
                            str(article.get("related") or "")
                            if article.get("related")
                            else None
                        ),
                    },
                    market=market,
                    summary=(
                        str(summary).strip()
                        if summary
                        else None
                    ),
                    effective_at=published_at,
                )
            )
        return items


def _symbols_for(market: str, ticker: str) -> Tuple[str, ...]:
    """Map a (ticker, market) pair to Finnhub symbol candidates."""
    normalized = ticker.strip().upper()
    if market == MARKET_HK:
        return (
            (normalized,)
            if normalized.endswith(".HK")
            else (f"{normalized}.HK",)
        )
    if market == MARKET_CN:
        if "." in normalized:
            return (normalized,)
        return (f"{normalized}.SS", f"{normalized}.SZ")
    return (normalized,)


def _dedupe_articles(
    items: Sequence[InformationItem],
) -> List[InformationItem]:
    by_identity: Dict[Tuple[str, str], InformationItem] = {}
    for item in items:
        by_identity.setdefault((item.external_id, item.url), item)
    return list(by_identity.values())


def _parse_unix_datetime(value: Any) -> Optional[datetime]:
    try:
        timestamp = int(value)
    except (TypeError, ValueError):
        return None
    return datetime.fromtimestamp(timestamp, tz=timezone.utc)


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
