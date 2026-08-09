"""TWSE OpenAPI material-information (重大訊息) client.

Live recon (2026-08-07): ``GET https://openapi.twse.com.tw/v1/opendata/
t187ap04_L`` returns a JSON array of listed-company material announcements
with traditional-Chinese keys (出表日期 / 發言日期 / 發言時間 / 公司代號 /
公司名稱 / 主旨(尾隨空白) / 符合條款 / 事實發生日 / 說明). Dates use ROC
calendar years (115 = 2026). The ``_O`` (TPEx) variant redirects and is not
covered; TPEx/興櫃 disclosure is left to TW-4.

From this network the endpoint works with the system trust store but Python's
strict TLS verification rejects the certificate (missing Subject Key
Identifier); the client keeps verification ON by default and offers
``TWSE_MATERIAL_VERIFY_SSL=false`` as an explicit opt-out for that quirk.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import ssl
import threading
import time
from datetime import date, datetime, time as dt_time, timezone
from typing import Any, Callable, Dict, List, Mapping, Optional, Tuple
from urllib.error import HTTPError, URLError
from urllib.request import HTTPSHandler, Request, build_opener, urlopen
from zoneinfo import ZoneInfo

from ...daily import date_only_market_noon

LOGGER = logging.getLogger(__name__)

DEFAULT_URL = "https://openapi.twse.com.tw/v1/opendata/t187ap04_L"
RETRYABLE_STATUS_CODES = frozenset({429, 500, 502, 503, 504})
DEFAULT_CACHE_TTL_SECONDS = 3600.0
TAIPEI = ZoneInfo("Asia/Taipei")
MOPS_QUERY_URL = "https://mops.twse.com.tw/mops/web/t05st09_ifrs"


class TwseMaterialError(Exception):
    """Base error for TWSE material-information collection."""


class TwseMaterialRequestError(TwseMaterialError):
    """Raised when a TWSE OpenAPI request cannot be completed."""


class TwseMaterialDataError(TwseMaterialError):
    """Raised when TWSE returns unexpected data."""


def normalize_tw_ticker(ticker: str) -> str:
    """Mirror ``web_repository.normalize_tw_ticker`` (kept in sync)."""
    cleaned = str(ticker).strip().upper()
    core = cleaned.removesuffix(".TW").removesuffix(".TWO")
    if core.isdigit():
        return core.lstrip("0").zfill(4)
    return cleaned


class TwseMaterialClient:
    """Small stdlib JSON client for the TWSE material-information dataset."""

    def __init__(
        self,
        url: str = DEFAULT_URL,
        timeout: float = 20.0,
        max_retries: int = 1,
        requests_per_second: float = 1.0,
        user_agent: str = "InvestmentMonitor/0.1 (internal workspace)",
        opener: Callable[..., Any] = urlopen,
        clock: Callable[[], float] = time.monotonic,
        sleeper: Callable[[float], None] = time.sleep,
        cache_ttl_seconds: float = DEFAULT_CACHE_TTL_SECONDS,
    ) -> None:
        if not url.strip():
            raise ValueError("TWSE material URL must not be empty.")
        if timeout <= 0:
            raise ValueError("TWSE material timeout must be greater than zero.")
        if max_retries < 0:
            raise ValueError("TWSE material max_retries must not be negative.")
        if requests_per_second <= 0:
            raise ValueError(
                "TWSE material requests_per_second must be greater than zero."
            )
        self._url = url.rstrip("/")
        self._timeout = timeout
        self._max_retries = max_retries
        self._minimum_interval = 1.0 / requests_per_second
        self._user_agent = user_agent
        self._opener = opener
        self._clock = clock
        self._sleeper = sleeper
        self._cache_ttl_seconds = cache_ttl_seconds
        self._last_request_at: Optional[float] = None
        self._rate_limit_lock = threading.Lock()
        self._daily_cache: Dict[str, Tuple[float, List[Mapping[str, Any]]]] = {}

    @classmethod
    def from_environment(cls) -> "TwseMaterialClient":
        verify_ssl = (
            os.environ.get("TWSE_MATERIAL_VERIFY_SSL", "true")
            .strip()
            .lower()
        ) not in {"0", "false", "no", "off"}
        opener: Callable[..., Any] = urlopen
        if not verify_ssl:
            opener = build_opener(
                HTTPSHandler(
                    context=ssl._create_unverified_context()
                )
            ).open
        return cls(
            url=os.environ.get("TWSE_MATERIAL_URL", DEFAULT_URL),
            timeout=_read_float_environment(
                "TWSE_MATERIAL_TIMEOUT_SECONDS",
                20.0,
            ),
            max_retries=_read_int_environment(
                "TWSE_MATERIAL_MAX_RETRIES",
                1,
            ),
            requests_per_second=_read_float_environment(
                "TWSE_MATERIAL_REQUESTS_PER_SECOND",
                1.0,
            ),
            opener=opener,
        )

    def fetch_material(self) -> List[Mapping[str, Any]]:
        """Fetch and cache the latest material-information table.

        A cached table that is still inside the short TTL is reused, so a
        multi-ticker collect does not re-download the whole table each time.
        """
        now = self._clock()
        for _key, (fetched_at, records) in self._daily_cache.items():
            if now - fetched_at <= self._cache_ttl_seconds:
                return records
        raw = self._get_json(self._url)
        records = _parse_records(raw, api_url=self._url)
        table_day = (
            records[0]["table_date"]
            if records
            else datetime.now(TAIPEI).date().isoformat()
        )
        self._daily_cache = {table_day: (now, records)}
        return records

    def _get_json(self, url: str) -> Any:
        for attempt in range(self._max_retries + 1):
            self._wait_for_rate_limit()
            request = Request(
                url,
                headers={
                    "User-Agent": self._user_agent,
                    "Accept": "application/json",
                    "Accept-Language": "zh-TW,en;q=0.8",
                },
                method="GET",
            )
            try:
                with self._opener(request, timeout=self._timeout) as response:
                    raw = response.read()
                return json.loads(raw.decode("utf-8", errors="replace"))
            except HTTPError as error:
                if (
                    error.code not in RETRYABLE_STATUS_CODES
                    or attempt == self._max_retries
                ):
                    raise TwseMaterialRequestError(
                        f"TWSE material request failed with HTTP "
                        f"{error.code}: {url}"
                    ) from error
            except URLError as error:
                if attempt == self._max_retries:
                    raise TwseMaterialRequestError(
                        f"TWSE material request failed after "
                        f"{self._max_retries + 1} attempts: {url}"
                    ) from error
            except TimeoutError as error:
                if attempt == self._max_retries:
                    raise TwseMaterialRequestError(
                        f"TWSE material request timed out after "
                        f"{self._max_retries + 1} attempts: {url}"
                    ) from error
            except (json.JSONDecodeError, UnicodeDecodeError) as error:
                raise TwseMaterialDataError(
                    "TWSE material response was not valid JSON."
                ) from error
            self._sleeper(0.5 * (2**attempt))
        raise TwseMaterialRequestError(f"TWSE material request failed: {url}")

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


def _parse_records(
    data: Any,
    *,
    api_url: str,
) -> List[Mapping[str, Any]]:
    if not isinstance(data, list):
        raise TwseMaterialDataError(
            "TWSE material response was not a JSON array."
        )
    records: List[Mapping[str, Any]] = []
    for row in data:
        if not isinstance(row, dict):
            continue
        code = normalize_tw_ticker(str(row.get("公司代號") or ""))
        title = str(
            row.get("主旨 ")
            or row.get("主旨")
            or ""
        ).strip()
        day = _parse_roc_date(str(row.get("發言日期") or ""))
        if not code or not title or day is None:
            continue
        time_text = str(row.get("發言時間") or "").strip()
        published_at = _parse_taipei_datetime(day, time_text)
        date_only = published_at is None
        if date_only:
            published_at = date_only_market_noon(day, TAIPEI)
        summary = _clean_text(str(row.get("說明") or ""))
        digest = hashlib.sha1(
            f"{code}|{day.isoformat()}|{time_text}|{title}".encode("utf-8")
        ).hexdigest()
        records.append(
            {
                "external_id": digest,
                "ticker": code,
                "title": title,
                "summary": summary,
                "published_at": published_at,
                "date_only": date_only,
                "calendar_date": day.isoformat(),
                "table_date": _roc_date_iso(str(row.get("出表日期") or ""))
                or day.isoformat(),
                "company_name": str(row.get("公司名稱") or "").strip(),
                "clause": str(row.get("符合條款") or "").strip(),
                "event_date": (
                    _roc_date_iso(str(row.get("事實發生日") or "")) or ""
                ),
                "raw": dict(row),
                "api_url": api_url,
            }
        )
    return records


def _parse_roc_date(value: str) -> Optional[date]:
    digits = re.sub(r"[^0-9]", "", value)
    if len(digits) != 7:
        return None
    try:
        return date(
            int(digits[0:3]) + 1911,
            int(digits[3:5]),
            int(digits[5:7]),
        )
    except ValueError:
        return None


def _roc_date_iso(value: str) -> str:
    parsed = _parse_roc_date(value)
    return parsed.isoformat() if parsed else ""


def _parse_taipei_datetime(
    day: date,
    time_text: str,
) -> Optional[datetime]:
    digits = re.sub(r"[^0-9]", "", time_text)
    if not digits:
        return None
    hms = digits.zfill(6)
    try:
        parsed = datetime.combine(
            day,
            dt_time(int(hms[0:2]), int(hms[2:4]), int(hms[4:6])),
            tzinfo=TAIPEI,
        )
    except ValueError:
        return None
    return parsed.astimezone(timezone.utc)


def _clean_text(value: str) -> Optional[str]:
    text = re.sub(r"\r\n|\r|\n", " ", value)
    text = re.sub(r"\s+", " ", text).strip()
    return text[:2000] or None


def _read_float_environment(name: str, default: float) -> float:
    value = os.environ.get(name)
    if value is None:
        return default
    try:
        return float(value)
    except ValueError:
        return default


def _read_int_environment(name: str, default: int) -> int:
    value = os.environ.get(name)
    if value is None:
        return default
    try:
        return int(value)
    except ValueError:
        return default
