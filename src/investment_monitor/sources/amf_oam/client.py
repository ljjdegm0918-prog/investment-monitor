"""AMF OAM disclosures JSON client.

The AMF OAM portal (oam-info.amf-france.org) publishes French regulated
disclosures through a key-free JSON API. This client fetches the raw
``/api/informations`` feed (successor to the public BDIF endpoint
``/back/api/v1/informations``) and returns the decoded JSON payload; the
connector owns record parsing and item mapping.

Date window: ``fetch_payload`` constrains the inclusive
``start_date``/``end_date`` window twice. The dates are sent as
``dateDebut``/``dateFin`` query parameters (the API family filters
``datePublication`` with an inclusive start and an exclusive end, so the
end day is sent as ``end_date + 1``) and, authoritatively, the fetched
records are filtered client-side by the Europe/Paris calendar day of the
publication timestamp before the payload is returned. The parameters are
never silently dropped.
"""

from __future__ import annotations

import json
import logging
import os
import time
from datetime import date, datetime, timedelta
from http.client import IncompleteRead
from typing import Any, Callable, Mapping, Optional
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

LOGGER = logging.getLogger(__name__)

DEFAULT_BASE_URL = "https://oam-info.amf-france.org/api"
_PARIS_ZONE = ZoneInfo("Europe/Paris")
RETRYABLE_STATUS_CODES = frozenset({429, 500, 502, 503, 504})


class AmfOamError(Exception):
    """Base error for AMF OAM collection."""


class AmfOamRequestError(AmfOamError):
    """Raised when the AMF OAM request cannot be completed."""


class AmfOamDataError(AmfOamError):
    """Raised when AMF OAM returns an unexpected payload."""


class AmfOamClient:
    """Key-free stdlib JSON client for the AMF OAM disclosures API."""

    def __init__(
        self,
        base_url: str = DEFAULT_BASE_URL,
        timeout: float = 45.0,
        max_retries: int = 3,
        requests_per_second: float = 1.0,
        user_agent: str = "InvestmentMonitor/0.1 (internal workspace)",
        opener: Callable[..., Any] = urlopen,
    ) -> None:
        if not base_url.strip() or timeout <= 0 or max_retries < 0:
            raise ValueError("AMF OAM client needs a valid URL and timeout.")
        self.base_url = base_url.rstrip("/")
        self._timeout = timeout
        self._max_retries = max_retries
        self._minimum_interval = 1.0 / max(requests_per_second, 0.01)
        self._user_agent = user_agent
        self._opener = opener
        self._last_request_at: Optional[float] = None

    @classmethod
    def from_environment(cls) -> "AmfOamClient":
        return cls(
            base_url=os.environ.get("AMF_OAM_URL", DEFAULT_BASE_URL),
            timeout=_env_float("AMF_OAM_TIMEOUT_SECONDS", 45.0),
            max_retries=_env_int("AMF_OAM_MAX_RETRIES", 3),
            requests_per_second=_env_float(
                "AMF_OAM_REQUESTS_PER_SECOND", 1.0
            ),
        )

    def fetch_payload(
        self,
        start_date: date,
        end_date: date,
        *,
        limit: int = 100,
    ) -> Any:
        """Fetch the AMF OAM ``informations`` payload for an inclusive window.

        The dates are sent as ``dateDebut``/``dateFin`` URL parameters (the
        API family filters ``datePublication`` with an inclusive start and
        an exclusive end, so the end day is sent as ``end_date + 1``) and
        the returned records are also filtered client-side by the
        Europe/Paris publication day, so ``start_date`` and ``end_date``
        genuinely constrain the result.
        """
        params = {"from": 0, "size": int(limit)}
        if start_date is not None:
            params["dateDebut"] = start_date.isoformat()
        if end_date is not None:
            params["dateFin"] = (end_date + timedelta(days=1)).isoformat()
        url = f"{self.base_url}/informations?{urlencode(params)}"
        payload = self._get_json(url)
        return _filter_payload_window(payload, start_date, end_date)

    def _get_json(self, url: str) -> Any:
        for attempt in range(self._max_retries + 1):
            self._throttle()
            request = Request(
                url,
                headers={
                    "User-Agent": self._user_agent,
                    "Accept": "application/json",
                },
                method="GET",
            )
            try:
                with self._opener(request, timeout=self._timeout) as response:
                    raw = response.read()
                try:
                    return json.loads(raw.decode("utf-8", errors="replace"))
                except json.JSONDecodeError as error:
                    raise AmfOamDataError(
                        "AMF OAM response is not valid JSON."
                    ) from error
            except AmfOamDataError:
                raise
            except IncompleteRead as error:
                if attempt == self._max_retries:
                    raise AmfOamRequestError(
                        f"AMF OAM incomplete read after "
                        f"{self._max_retries + 1} attempts: {url}"
                    ) from error
            except HTTPError as error:
                if (
                    error.code not in RETRYABLE_STATUS_CODES
                    or attempt == self._max_retries
                ):
                    raise AmfOamRequestError(
                        f"AMF OAM request failed with HTTP {error.code}: {url}"
                    ) from error
            except (URLError, TimeoutError) as error:
                if attempt == self._max_retries:
                    raise AmfOamRequestError(
                        f"AMF OAM request failed after "
                        f"{self._max_retries + 1} attempts: {url}"
                    ) from error
            time.sleep(0.5 * (2**attempt))
        raise AmfOamRequestError(f"AMF OAM request failed: {url}")

    def _throttle(self) -> None:
        now = time.monotonic()
        if self._last_request_at is not None:
            remaining = self._minimum_interval - (now - self._last_request_at)
            if remaining > 0:
                time.sleep(remaining)
        self._last_request_at = time.monotonic()


def _filter_payload_window(
    payload: Any,
    start_date: Optional[date],
    end_date: Optional[date],
) -> Any:
    """Drop records outside the inclusive window, preserving payload shape.

    Both accepted shapes are filtered in place: a plain ``result`` list and
    an Elasticsearch ``hits.hits[]._source`` wrapper. Unrecognized payloads
    are returned unchanged (the connector reports no records for them).
    """
    if start_date is None and end_date is None:
        return payload
    if not isinstance(payload, dict):
        return payload

    def keep(record: Any) -> bool:
        if not isinstance(record, dict):
            return False
        published = _parse_publication_datetime(record)
        if published is None:
            return False
        day = _paris_day(published)
        return (start_date is None or start_date <= day) and (
            end_date is None or end_date >= day
        )

    result = payload.get("result")
    if isinstance(result, list):
        filtered = [record for record in result if keep(record)]
        return dict(payload, result=filtered)
    hits = payload.get("hits")
    if isinstance(hits, dict) and isinstance(hits.get("hits"), list):
        rows = [
            row
            for row in hits["hits"]
            if isinstance(row, dict) and keep(row.get("_source"))
        ]
        return dict(payload, hits=dict(hits, hits=rows))
    return payload


def _parse_publication_datetime(record: Mapping[str, Any]) -> Optional[datetime]:
    value = (
        record.get("datePublication")
        or record.get("dateMiseEnLigne")
        or record.get("dateInformation")
    )
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None


def _paris_day(value: datetime) -> date:
    """Return the Europe/Paris calendar day of a publication timestamp.

    Naive timestamps from the AMF feed are market-local Paris times, so
    their calendar day is used directly; aware timestamps are converted to
    Europe/Paris before taking the day.
    """
    if value.tzinfo is None:
        return value.date()
    return value.astimezone(_PARIS_ZONE).date()


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
