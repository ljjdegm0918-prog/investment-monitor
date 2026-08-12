"""BME relevant-facts JSON client (Spain).

Recon (verified live 2026-08-10): ``GET https://apiweb.bolsasymercados.es/
Market/v1/EQ/RelevantFacts?companyKey=13900&from=YYYYMMDD&to=YYYYMMDD``
returns the key-free JSON used by the official BME "hechos relevantes"
pages: ``data[]`` with ``issuerName``, ``issuerKey`` (BME company key from
the ES universe), ``cnmvRegNumber`` (stable CNMV registration number, ``IP``
or ``OI`` prefixed), ``relevantFactDate`` (YYYYMMDD), ``relevantFactTitle``,
``relevantFactText`` and a relative PDF path. The API clamps the requested
range to at most ~31 calendar days and filters the records to that window;
the client also filters client-side by the inclusive requested window, so a
30-day lookback fits but older history is not available from this endpoint.
This is an official BME API (same family as the ES universe), key-free and
without login; like the universe endpoint it is undocumented and may change
without notice. Records are date-only, so collection timestamps use the
Europe/Madrid noon anchor convention.
"""

from __future__ import annotations

import json
import logging
import os
import re
import threading
import time
from datetime import date, datetime, timedelta, timezone
from typing import Any, Callable, List, Mapping, Optional
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

LOGGER = logging.getLogger(__name__)

MADRID = ZoneInfo("Europe/Madrid")
DEFAULT_BASE_URL = (
    "https://apiweb.bolsasymercados.es/Market/v1/EQ/RelevantFacts"
)
RETRYABLE_STATUS_CODES = frozenset({429, 500, 502, 503, 504})
_REG_NUMBER_RE = re.compile(r"([A-Z]+)(\d+)")


class BmeRelevantFactsError(Exception):
    """Base error for BME relevant-facts collection."""


class BmeRelevantFactsRequestError(BmeRelevantFactsError):
    """Raised when the BME relevant-facts request cannot be completed."""


class BmeRelevantFactsDataError(BmeRelevantFactsError):
    """Raised when BME returns an unexpected payload."""


class BmeRelevantFactsClient:
    """Small stdlib JSON client for BME relevant facts by company key."""

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
            raise ValueError("BME relevant-facts base URL must not be empty.")
        if timeout <= 0:
            raise ValueError(
                "BME relevant-facts timeout must be greater than zero."
            )
        if max_retries < 0:
            raise ValueError(
                "BME relevant-facts max_retries must not be negative."
            )
        if requests_per_second <= 0:
            raise ValueError(
                "BME relevant-facts requests_per_second must be greater "
                "than zero."
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
    def from_environment(cls) -> "BmeRelevantFactsClient":
        return cls(
            base_url=os.environ.get(
                "BME_RELEVANT_FACTS_URL",
                DEFAULT_BASE_URL,
            ),
            timeout=_read_float_environment(
                "BME_RELEVANT_FACTS_TIMEOUT_SECONDS", 20.0
            ),
            max_retries=_read_int_environment(
                "BME_RELEVANT_FACTS_MAX_RETRIES", 1
            ),
            requests_per_second=_read_float_environment(
                "BME_RELEVANT_FACTS_REQUESTS_PER_SECOND", 1.0
            ),
        )

    def fetch_by_company(
        self,
        company_key: str,
        start_date: date,
        end_date: date,
        *,
        max_pages: int = 5,
        max_chunk_days: int = 31,
    ) -> List[Mapping[str, Any]]:
        """Fetch and parse relevant facts for a BME company key.

        The BME API clamps each request to at most ~31 calendar days, so
        longer windows are fetched in consecutive chunks and merged.
        """
        records: List[Mapping[str, Any]] = []
        seen: set[str] = set()
        for chunk_start, chunk_end in _date_chunks(
            start_date,
            end_date,
            max_chunk_days=max_chunk_days,
        ):
            for page in range(1, max_pages + 1):
                url = (
                    f"{self._base_url}?companyKey={quote(company_key)}"
                    f"&from={chunk_start:%Y%m%d}&to={chunk_end:%Y%m%d}"
                    f"&page={page}&pageSize=50"
                )
                payload = self._get_json(url)
                page_records = _parse_payload(
                    payload,
                    start_date=start_date,
                    end_date=end_date,
                )
                for record in page_records:
                    key = str(record.get("external_id") or "")
                    if key and key in seen:
                        continue
                    if key:
                        seen.add(key)
                    records.append({**record, "retrieval_url": url})
                if not _has_more(payload):
                    break
                if page == max_pages:
                    raise BmeRelevantFactsDataError(
                        "BME relevant-facts results exceed "
                        f"max_pages={max_pages} for companyKey={company_key}."
                    )
        return records

    def _get_json(self, url: str) -> Any:
        for attempt in range(self._max_retries + 1):
            self._wait_for_rate_limit()
            request = Request(
                url,
                headers={
                    "User-Agent": self._user_agent,
                    "Accept": "application/json",
                    "Accept-Language": "es-ES,en;q=0.9",
                },
                method="GET",
            )
            try:
                with self._opener(request, timeout=self._timeout) as response:
                    raw = response.read()
                try:
                    return json.loads(raw.decode("utf-8", errors="replace"))
                except json.JSONDecodeError as error:
                    raise BmeRelevantFactsDataError(
                        "BME relevant-facts response is not valid JSON."
                    ) from error
            except BmeRelevantFactsDataError:
                raise
            except HTTPError as error:
                if (
                    error.code not in RETRYABLE_STATUS_CODES
                    or attempt == self._max_retries
                ):
                    raise BmeRelevantFactsRequestError(
                        f"BME relevant-facts request failed with HTTP "
                        f"{error.code}: {url}"
                    ) from error
            except URLError as error:
                if attempt == self._max_retries:
                    raise BmeRelevantFactsRequestError(
                        f"BME relevant-facts request failed after "
                        f"{self._max_retries + 1} attempts: {url}"
                    ) from error
            except TimeoutError as error:
                if attempt == self._max_retries:
                    raise BmeRelevantFactsRequestError(
                        f"BME relevant-facts request timed out after "
                        f"{self._max_retries + 1} attempts: {url}"
                    ) from error
            self._sleeper(0.5 * (2**attempt))
        raise BmeRelevantFactsRequestError(
            f"BME relevant-facts request failed: {url}"
        )

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


def _date_chunks(
    start_date: date,
    end_date: date,
    *,
    max_chunk_days: int,
) -> List[tuple[date, date]]:
    """Split an inclusive date range into BME-sized chunks."""
    if max_chunk_days <= 0:
        raise ValueError("max_chunk_days must be positive.")
    chunks: List[tuple[date, date]] = []
    cursor = start_date
    step = timedelta(days=max_chunk_days - 1)
    while cursor <= end_date:
        chunk_end = min(end_date, cursor + step)
        chunks.append((cursor, chunk_end))
        cursor = chunk_end + timedelta(days=1)
    return chunks


def _parse_payload(
    payload: Any,
    *,
    start_date: date,
    end_date: date,
) -> List[Mapping[str, Any]]:
    if not isinstance(payload, Mapping):
        raise BmeRelevantFactsDataError(
            "BME relevant-facts response was not a JSON object."
        )
    data = payload.get("data")
    if not isinstance(data, list):
        raise BmeRelevantFactsDataError(
            "BME relevant-facts response had no data list."
        )
    records: List[Mapping[str, Any]] = []
    for item in data:
        if not isinstance(item, Mapping):
            continue
        reg_raw = str(item.get("cnmvRegNumber") or "").strip()
        title = str(item.get("relevantFactTitle") or "").strip()
        day = _parse_day(str(item.get("relevantFactDate") or ""))
        if not reg_raw or not title or day is None:
            continue
        if day < start_date or day > end_date:
            continue
        prefix, digits = _split_reg_number(reg_raw)
        external_id = f"{prefix}:{digits}" if prefix else digits
        records.append(
            {
                "external_id": external_id,
                "prefix": prefix,
                "nreg": digits,
                "cnmv_reg_number": reg_raw,
                "day": day,
                "title": title,
                "text": str(item.get("relevantFactText") or "").strip(),
                "code": str(item.get("relevantFactCode") or "").strip(),
                "issuer_name": str(item.get("issuerName") or "").strip(),
                "pdf_url": str(item.get("pdfurl") or "").strip(),
                "url": _detail_url(prefix, digits),
                "published_at_raw": str(
                    item.get("relevantFactDate") or ""
                ),
                "raw_payload": dict(item),
            }
        )
    return records


def _split_reg_number(value: str) -> tuple:
    match = _REG_NUMBER_RE.match(value)
    if match is None:
        digits = re.sub(r"\D", "", value)
        return "", digits
    return match.group(1), str(int(match.group(2)))


def _detail_url(prefix: str, digits: str) -> str:
    if prefix.upper() == "IP":
        return (
            "https://www.cnmv.es/Portal/Informacion-privilegiada/"
            f"Resultado-IP.aspx?nreg={digits}"
        )
    if prefix.upper() == "OI":
        return (
            "https://www.cnmv.es/Portal/Otra-Informacion-Relevante/"
            f"Resultado-OIR.aspx?nreg={digits}"
        )
    return "https://www.cnmv.es/Portal/Informacion-privilegiada/AlDia-IP.aspx"


def _parse_day(value: str) -> Optional[date]:
    if not value:
        return None
    try:
        return datetime.strptime(value, "%Y%m%d").date()
    except ValueError:
        return None


def _has_more(payload: Any) -> bool:
    if not isinstance(payload, Mapping):
        return False
    data = payload.get("data")
    if not isinstance(data, list):
        return False
    return bool(len(data) >= 50 and payload.get("hasMoreResults"))


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
