"""CNMV official relevant-information RSS client (Spain).

Recon (verified live 2026-08-10): the CNMV publishes two key-free RSS 2.0
feeds for Spanish issuers' disclosures:

* ``informacion-privilegiada`` (inside information / hechos relevantes):
  ``GET https://www.cnmv.es/portal/informacion-privilegiada/RSS.asmx/GetNoticiasCNMV``
* ``Otra-Informacion-Relevante`` (other relevant information):
  ``GET https://www.cnmv.es/portal/Otra-Informacion-Relevante/RSS.asmx/GetNoticiasCNMV``

Both return RSS items whose ``Title`` is the issuer legal name and whose
``link``/``guid`` is a permanent CNMV detail URL carrying ``nreg=NNNN`` (a
stable registration number). ``pubDate`` is RFC-822 GMT; the description is
CDATA HTML with a Europe/Madrid local time, a category and the announcement
text. The IP feed is currently empty on some days (no items is honest, not
a failure). The feeds are official, key-free and stable; the site
certificate chain has been seen to fail intermittently in this workspace,
so TLS verification stays ON by default with an explicit per-connector
``CNMV_HR_VERIFY_SSL`` opt-out (default true) for users behind that quirk.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import html
import logging
import os
import re
import ssl
import threading
import time
from datetime import date, datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Any, Callable, List, Mapping, Optional, Tuple
from urllib.error import HTTPError, URLError
from urllib.request import HTTPSHandler, Request, build_opener, urlopen
from zoneinfo import ZoneInfo
import xml.etree.ElementTree as ElementTree

LOGGER = logging.getLogger(__name__)

MADRID = ZoneInfo("Europe/Madrid")
DEFAULT_IP_URL = (
    "https://www.cnmv.es/portal/informacion-privilegiada/"
    "RSS.asmx/GetNoticiasCNMV"
)
DEFAULT_OIR_URL = (
    "https://www.cnmv.es/portal/Otra-Informacion-Relevante/"
    "RSS.asmx/GetNoticiasCNMV"
)
RETRYABLE_STATUS_CODES = frozenset({429, 500, 502, 503, 504})
_NREG_RE = re.compile(r"nreg=(\d+)")
_LOCAL_TIME_RE = re.compile(
    r"(\d{2}):(\d{2})\s+(\d{2})/(\d{2})/(\d{4})"
)


class CnmvHrError(Exception):
    """Base error for CNMV relevant-information collection."""


class CnmvHrRequestError(CnmvHrError):
    """Raised when the CNMV RSS request cannot be completed."""


class CnmvHrDataError(CnmvHrError):
    """Raised when CNMV returns an unexpected feed."""


@dataclass(frozen=True)
class CnmvHrFeedOutcome:
    """One truthful CNMV feed attempt and its usable records."""

    feed_id: str
    status: str
    records_read: int
    retrieval_url: str
    finished_at: datetime
    error_kind: Optional[str] = None
    error_message: Optional[str] = None


@dataclass(frozen=True)
class CnmvHrFetchResult:
    """Structured outcome for the independent IP and OIR feed attempts."""

    records: Tuple[Mapping[str, Any], ...]
    feed_outcomes: Tuple[CnmvHrFeedOutcome, ...]

    @property
    def status(self) -> str:
        failed = sum(
            feed.status == "failure" for feed in self.feed_outcomes
        )
        if failed == len(self.feed_outcomes):
            return "failure"
        if failed:
            return "partial"
        if any(feed.status == "success" for feed in self.feed_outcomes):
            return "success"
        return "empty"


class CnmvHrClient:
    """Small stdlib RSS client for the two CNMV disclosure feeds."""

    def __init__(
        self,
        ip_url: str = DEFAULT_IP_URL,
        oir_url: str = DEFAULT_OIR_URL,
        timeout: float = 20.0,
        max_retries: int = 1,
        requests_per_second: float = 1.0,
        user_agent: str = "InvestmentMonitor/0.1 (internal workspace)",
        opener: Callable[..., Any] = urlopen,
        clock: Callable[[], float] = time.monotonic,
        sleeper: Callable[[float], None] = time.sleep,
    ) -> None:
        if not ip_url.strip() or not oir_url.strip():
            raise ValueError("CNMV HR feed URLs must not be empty.")
        if timeout <= 0:
            raise ValueError("CNMV HR timeout must be greater than zero.")
        if max_retries < 0:
            raise ValueError("CNMV HR max_retries must not be negative.")
        if requests_per_second <= 0:
            raise ValueError(
                "CNMV HR requests_per_second must be greater than zero."
            )
        self._ip_url = ip_url.strip()
        self._oir_url = oir_url.strip()
        self._timeout = timeout
        self._max_retries = max_retries
        self._minimum_interval = 1.0 / requests_per_second
        self._user_agent = user_agent
        self._opener = opener
        self._clock = clock
        self._sleeper = sleeper
        self._last_request_at: Optional[float] = None
        self._rate_limit_lock = threading.Lock()
        self._last_result: Optional[CnmvHrFetchResult] = None

    @classmethod
    def from_environment(cls) -> "CnmvHrClient":
        return cls(
            ip_url=os.environ.get("CNMV_HR_IP_URL", DEFAULT_IP_URL),
            oir_url=os.environ.get("CNMV_HR_OIR_URL", DEFAULT_OIR_URL),
            timeout=_read_float_environment("CNMV_HR_TIMEOUT_SECONDS", 20.0),
            max_retries=_read_int_environment("CNMV_HR_MAX_RETRIES", 1),
            requests_per_second=_read_float_environment(
                "CNMV_HR_REQUESTS_PER_SECOND", 1.0
            ),
            opener=_opener_from_environment(),
        )

    def fetch_disclosures(
        self,
        start_date: date,
        end_date: date,
    ) -> CnmvHrFetchResult:
        """Fetch both CNMV feeds and return their independent outcomes.

        One feed failing (network, HTTP error or malformed XML) is logged and
        does not discard records from the other feed. Both feeds failing and
        both feeds being empty are represented explicitly without raising.
        """
        return self.fetch_disclosures_result(start_date, end_date)

    @property
    def last_result(self) -> Optional[CnmvHrFetchResult]:
        return self._last_result

    def fetch_disclosures_result(
        self,
        start_date: date,
        end_date: date,
    ) -> CnmvHrFetchResult:
        """Fetch IP and OIR independently without discarding partial success."""
        feed_outcomes: List[CnmvHrFeedOutcome] = []
        collected: List[Mapping[str, Any]] = []
        for feed, url in (("ip", self._ip_url), ("oir", self._oir_url)):
            try:
                body = self._get_xml(url)
                records = tuple(_parse_rss(
                    body,
                    start_date=start_date,
                    end_date=end_date,
                ))
                collected.extend(records)
                feed_outcomes.append(CnmvHrFeedOutcome(
                    feed_id=feed,
                    status="success" if records else "empty",
                    records_read=len(records),
                    retrieval_url=url,
                    finished_at=datetime.now(timezone.utc),
                ))
            except CnmvHrRequestError as error:
                feed_outcomes.append(CnmvHrFeedOutcome(
                    feed_id=feed,
                    status="failure",
                    records_read=0,
                    retrieval_url=url,
                    finished_at=datetime.now(timezone.utc),
                    error_kind="request",
                    error_message=str(error),
                ))
                LOGGER.warning(
                    "cnmv_hr feed=%s url=%s status=failure error=%s",
                    feed,
                    url,
                    error,
                )
            except CnmvHrDataError as error:
                feed_outcomes.append(CnmvHrFeedOutcome(
                    feed_id=feed,
                    status="failure",
                    records_read=0,
                    retrieval_url=url,
                    finished_at=datetime.now(timezone.utc),
                    error_kind="data",
                    error_message=str(error),
                ))
                LOGGER.warning(
                    "cnmv_hr feed=%s url=%s status=data_error error=%s",
                    feed,
                    url,
                    error,
                )
        result = CnmvHrFetchResult(
            records=tuple(collected),
            feed_outcomes=tuple(feed_outcomes),
        )
        self._last_result = result
        return result

    def _get_xml(self, url: str) -> bytes:
        for attempt in range(self._max_retries + 1):
            self._wait_for_rate_limit()
            request = Request(
                url,
                headers={
                    "User-Agent": self._user_agent,
                    "Accept-Language": "es-ES,en;q=0.9",
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
                    raise CnmvHrRequestError(
                        f"CNMV HR request failed with HTTP "
                        f"{error.code}: {url}"
                    ) from error
            except URLError as error:
                if attempt == self._max_retries:
                    raise CnmvHrRequestError(
                        f"CNMV HR request failed after "
                        f"{self._max_retries + 1} attempts: {url}"
                    ) from error
            except TimeoutError as error:
                if attempt == self._max_retries:
                    raise CnmvHrRequestError(
                        f"CNMV HR request timed out after "
                        f"{self._max_retries + 1} attempts: {url}"
                    ) from error
            self._sleeper(0.5 * (2**attempt))
        raise CnmvHrRequestError(f"CNMV HR request failed: {url}")

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


def madrid_day(value: datetime) -> date:
    """Calendar day in Europe/Madrid for an aware/naive UTC datetime."""
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(MADRID).date()


def _parse_rss(
    body: bytes,
    *,
    start_date: date,
    end_date: date,
) -> List[Mapping[str, Any]]:
    try:
        root = ElementTree.fromstring(body)
    except ElementTree.ParseError as error:
        raise CnmvHrDataError(
            "CNMV HR response is not valid XML."
        ) from error
    if _local_name(root.tag).lower() != "rss":
        raise CnmvHrDataError("CNMV HR response is not an RSS feed.")
    records: List[Mapping[str, Any]] = []
    for item in root.iter():
        if _local_name(item.tag).lower() != "item":
            continue
        company = _child_text(item, "title")
        link = _child_text(item, "link")
        guid = _child_text(item, "guid") or link
        if not company or not link:
            continue
        published = _parse_rfc822(_child_text(item, "pubDate"))
        if published is None:
            continue
        day = madrid_day(published)
        if day < start_date or day > end_date:
            continue
        category, text, local_time = _parse_description(
            _child_text(item, "description")
        )
        nreg = _nreg(guid or link)
        external_id = (
            nreg
            if nreg
            else hashlib.sha1(
                str(guid or link).encode("utf-8")
            ).hexdigest()
        )
        records.append(
            {
                "external_id": external_id,
                "nreg": nreg,
                "company_name": html.unescape(company).strip(),
                "url": str(link).strip(),
                "published": published,
                "effective": local_time or published,
                "category": category,
                "text": text,
            }
        )
    return records


def _parse_description(
    value: str,
) -> Tuple[str, str, Optional[datetime]]:
    """Split a CNMV RSS description into category, text and Madrid time."""
    text = str(value or "")
    category = ""
    body_text = ""
    local_time: Optional[datetime] = None
    bold = re.search(r"<b[^>]*>(.*?)</b>", text, re.I | re.S)
    if bold is not None:
        local_time = _parse_local_time(_strip_tags(bold.group(1)))
        rest = text[bold.end():]
        parts = re.split(r"<br\s*/?>", rest, flags=re.I)
        category = _strip_tags(parts[0]).strip()
        if len(parts) > 1:
            tail = " ".join(
                _strip_tags(part) for part in parts[1:]
            )
            body_text = re.sub(r"\s+", " ", tail).strip()
    else:
        category = _strip_tags(text).strip()
    return category, body_text, local_time


def _parse_local_time(value: str) -> Optional[datetime]:
    match = _LOCAL_TIME_RE.search(str(value or ""))
    if match is None:
        return None
    hour, minute, day, month, year = (
        int(match.group(1)),
        int(match.group(2)),
        int(match.group(3)),
        int(match.group(4)),
        int(match.group(5)),
    )
    try:
        return datetime(
            year, month, day, hour, minute, tzinfo=MADRID
        )
    except ValueError:
        return None


def _parse_rfc822(value: str) -> Optional[datetime]:
    try:
        parsed = parsedate_to_datetime(str(value or "").strip())
    except (TypeError, ValueError):
        return None
    return parsed


def _nreg(value: str) -> str:
    match = _NREG_RE.search(str(value or ""))
    return match.group(1) if match else ""


def _strip_tags(value: str) -> str:
    text = html.unescape(re.sub(r"<[^>]+>", " ", str(value or "")))
    return re.sub(r"\s+", " ", text).strip()


def _child_text(element: Any, local_name: str) -> str:
    for child in element:
        if _local_name(child.tag).lower() == local_name.lower():
            return child.text or ""
    return ""


def _local_name(tag: Any) -> str:
    return str(tag).split("}")[-1]


def _opener_from_environment() -> Callable[..., Any]:
    verify_ssl = (
        os.environ.get("CNMV_HR_VERIFY_SSL", "true")
        .strip()
        .lower()
    ) not in {"0", "false", "no", "off"}
    if verify_ssl:
        return urlopen
    return build_opener(
        HTTPSHandler(context=ssl._create_unverified_context())
    ).open


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
