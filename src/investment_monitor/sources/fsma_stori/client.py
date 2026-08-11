"""FSMA STORI key-free JSON client for Belgian issuer disclosures.

Recon (verified live 2026-08-10):
``POST https://webapi.fsma.be/api/v1/en/stori/result`` with a JSON body
``{startRowIndex, pageSize, sortDirection, sortColumn, isinCode,
publicationStart, publicationEnd}`` returns
``{resultCount, storiResultItems:[...]}`` with a stable document id
(``requiredReportingTopicId`` UUID), ``companyName``, ``reportingTopicName``,
``datePublication``/``dateReceived`` (naive Europe/Brussels local time),
``lei``, ``isinCodes`` and ``mainDocuments``/``attachments``. No API key,
no login, no paid wall. The same surface powers the official STORI portal
(``https://www.fsma.be/en/stori``), the Belgian central storage mechanism
for regulated information run by the FSMA (submissions since 1 Jan 2011) -
the Belgian counterpart of the AMF OAM feed. The JSON surface is
undocumented and may change without notice.

Date window: the client sends ``publicationStart``/``publicationEnd`` to the
API and, authoritatively, filters fetched records client-side by the
Europe/Brussels calendar day of ``datePublication`` before returning them,
so ``start_date``/``end_date`` genuinely constrain the result.

BE-4 boundary (re-verified live 2026-08-10): no stable key-free second
Belgian disclosure source exists. Euronext Brussels announcements are Drupal
HTML pages keyed by per-company node IDs (no RSS, no JSON export;
``_format=json`` returns 406); the key-free EQS News JSON API returns zero
records for sampled Belgian ISINs including BEL 20 names. Paid feeds
(Euronext Web Services/Saturn, FinancialReports.eu, LSEG) are not wired.
FSMA STORI stays the only wired BE disclosure source.
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
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

LOGGER = logging.getLogger(__name__)

BRUSSELS = ZoneInfo("Europe/Brussels")
DEFAULT_BASE_URL = "https://webapi.fsma.be/api/v1"
DEFAULT_LANGUAGE = "en"
DEFAULT_PUBLIC_PORTAL = "https://www.fsma.be/en/stori"
RETRYABLE_STATUS_CODES = frozenset({429, 500, 502, 503, 504})
_ISIN_RE = re.compile(r"^BE[0-9]{10}$")


class StoriError(Exception):
    """Base error for FSMA STORI collection."""


class StoriRequestError(StoriError):
    """Raised when the STORI request cannot be completed."""


class StoriDataError(StoriError):
    """Raised when STORI returns unexpected JSON."""


class StoriClient:
    """Small stdlib JSON client for the FSMA STORI disclosures API."""

    def __init__(
        self,
        base_url: str = DEFAULT_BASE_URL,
        language: str = DEFAULT_LANGUAGE,
        timeout: float = 20.0,
        max_retries: int = 1,
        requests_per_second: float = 1.0,
        user_agent: str = "InvestmentMonitor/0.1 (internal workspace)",
        opener: Callable[..., Any] = urlopen,
        clock: Callable[[], float] = time.monotonic,
        sleeper: Callable[[float], None] = time.sleep,
    ) -> None:
        if not base_url.strip() or not language.strip():
            raise ValueError("STORI needs a base URL and a language code.")
        if timeout <= 0:
            raise ValueError("STORI timeout must be greater than zero.")
        if max_retries < 0:
            raise ValueError("STORI max_retries must not be negative.")
        if requests_per_second <= 0:
            raise ValueError(
                "STORI requests_per_second must be greater than zero."
            )
        self._base_url = base_url.rstrip("/")
        self._language = language.strip().lower()
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
    def from_environment(cls) -> "StoriClient":
        return cls(
            base_url=os.environ.get("FSMA_STORI_URL", DEFAULT_BASE_URL),
            language=os.environ.get(
                "FSMA_STORI_LANGUAGE", DEFAULT_LANGUAGE
            ),
            timeout=_env_float("FSMA_STORI_TIMEOUT_SECONDS", 20.0),
            max_retries=_env_int("FSMA_STORI_MAX_RETRIES", 1),
            requests_per_second=_env_float(
                "FSMA_STORI_REQUESTS_PER_SECOND", 1.0
            ),
        )

    @property
    def result_url(self) -> str:
        """URL of the STORI search endpoint for this client."""
        return f"{self._base_url}/{self._language}/stori/result"

    def download_url(self, file_data_id: str) -> str:
        """Deep link to a STORI document download (key-free, verified 200)."""
        return (
            f"{self._base_url}/{self._language}/stori/download"
            f"?{urlencode({'fileDataId': str(file_data_id or '').strip()})}"
        )

    def fetch_by_isin(
        self,
        isin: str,
        start_date: date,
        end_date: date,
        *,
        page_size: int = 100,
        max_pages: int = 10,
    ) -> List[Mapping[str, Any]]:
        """Fetch STORI disclosures for a Belgian ISIN in an inclusive window."""
        code = str(isin or "").strip().upper()
        if not _ISIN_RE.match(code):
            raise ValueError("STORI ISIN must look like BE + 10 digits.")
        params = {
            "pageSize": int(page_size),
            "isinCode": code,
        }
        return self._search(params, start_date, end_date, max_pages=max_pages)

    def fetch_by_company_name(
        self,
        company_name: str,
        start_date: date,
        end_date: date,
        *,
        page_size: int = 100,
        max_pages: int = 10,
    ) -> List[Mapping[str, Any]]:
        """Fetch STORI disclosures matching a company name in a window.

        The API matches company names loosely (verified live: ``KBC`` also
        returns KBC GROUP / KBC ANCORA), so every returned record is
        re-verified client-side by the connector matcher before it becomes
        an item. The ticker mnemonic is never passed as a company name.
        """
        name = str(company_name or "").strip()
        if len(name) < 3:
            raise ValueError("STORI company name is too short.")
        params = {
            "pageSize": int(page_size),
            "companyName": name,
        }
        return self._search(params, start_date, end_date, max_pages=max_pages)

    def _search(
        self,
        params: Mapping[str, Any],
        start_date: date,
        end_date: date,
        *,
        max_pages: int,
    ) -> List[Mapping[str, Any]]:
        collected: List[Mapping[str, Any]] = []
        page_size = max(1, int(params.get("pageSize") or 100))
        expected_total: Optional[int] = None
        rows_seen = 0
        for page in range(max_pages):
            body = dict(params)
            body["startRowIndex"] = page * page_size
            body["sortDirection"] = "Ascending"
            body["publicationStart"] = start_date.isoformat()
            body["publicationEnd"] = end_date.isoformat()
            payload = self._post_json(self.result_url, body)
            if not isinstance(payload, Mapping):
                raise StoriDataError(
                    f"STORI JSON root must be an object for {self.result_url}"
                )
            rows = payload.get("storiResultItems")
            if not isinstance(rows, list):
                raise StoriDataError(
                    "STORI response is missing storiResultItems."
                )
            total = payload.get("resultCount")
            if isinstance(total, int):
                expected_total = total
            rows_seen += len(rows)
            for raw in rows:
                parsed = _parse_record(raw)
                if parsed is not None:
                    collected.append({
                        **parsed,
                        "retrieval_url": self.result_url,
                    })
            if not rows or len(rows) < page_size:
                break
            if expected_total is not None and rows_seen >= expected_total:
                break
            if page == max_pages - 1:
                if expected_total is not None:
                    raise StoriDataError(
                        "STORI results exceed "
                        f"max_pages={max_pages}: "
                        f"received {rows_seen} of {expected_total} rows."
                    )
                probe_body = dict(body)
                probe_body["startRowIndex"] = max_pages * page_size
                probe_payload = self._post_json(self.result_url, probe_body)
                if not isinstance(probe_payload, Mapping):
                    raise StoriDataError(
                        "STORI pagination probe JSON root must be an object."
                    )
                probe_rows = probe_payload.get("storiResultItems")
                if not isinstance(probe_rows, list):
                    raise StoriDataError(
                        "STORI pagination probe is missing storiResultItems."
                    )
                if probe_rows:
                    raise StoriDataError(
                        f"STORI results exceed max_pages={max_pages}."
                    )
        # Authoritative client-side window filter by Brussels calendar day.
        return [
            record
            for record in collected
            if start_date <= brussels_day(record["published"]) <= end_date
        ]

    def _post_json(
        self, url: str, body: Mapping[str, Any]
    ) -> Any:
        encoded = json.dumps(body, separators=(",", ":")).encode("utf-8")
        for attempt in range(self._max_retries + 1):
            self._wait_for_rate_limit()
            request = Request(
                url,
                data=encoded,
                headers={
                    "User-Agent": self._user_agent,
                    "Accept": "application/json",
                    "Content-Type": "application/json",
                },
                method="POST",
            )
            try:
                with self._opener(request, timeout=self._timeout) as response:
                    raw = response.read()
                try:
                    return json.loads(raw.decode("utf-8", errors="replace"))
                except json.JSONDecodeError as error:
                    raise StoriDataError(
                        "STORI response is not valid JSON."
                    ) from error
            except StoriDataError:
                raise
            except HTTPError as error:
                if (
                    error.code not in RETRYABLE_STATUS_CODES
                    or attempt == self._max_retries
                ):
                    raise StoriRequestError(
                        f"STORI request failed with HTTP {error.code}: {url}"
                    ) from error
            except (URLError, TimeoutError) as error:
                if attempt == self._max_retries:
                    raise StoriRequestError(
                        f"STORI request failed after "
                        f"{self._max_retries + 1} attempts: {url}"
                    ) from error
            self._sleeper(0.5 * (2**attempt))
        raise StoriRequestError(f"STORI request failed: {url}")

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


def brussels_day(value: datetime) -> date:
    """Calendar day in Europe/Brussels for a naive/aware datetime.

    Naive timestamps from the STORI feed are Brussels-local publication
    times (the portal renders them directly), so their calendar day is used
    as-is; aware timestamps are converted to Europe/Brussels first.
    """
    if value.tzinfo is None:
        return value.date()
    return value.astimezone(BRUSSELS).date()


def _parse_record(raw: Any) -> Optional[Mapping[str, Any]]:
    if not isinstance(raw, Mapping):
        return None
    external_id = str(raw.get("requiredReportingTopicId") or "").strip()
    published = _parse_datetime(str(raw.get("datePublication") or ""))
    if not external_id or published is None:
        return None
    topic = str(raw.get("reportingTopicName") or "").strip()
    title = str(raw.get("documentTitle") or "").strip() or topic or "disclosure"
    company = str(raw.get("companyName") or "").strip()
    documents = [
        document
        for document in (
            _parse_document(item)
            for item in raw.get("mainDocuments")
            if isinstance(item, Mapping)
        )
        if document is not None
    ]
    attachments = [
        document
        for document in (
            _parse_document(item)
            for item in raw.get("attachments")
            if isinstance(item, Mapping)
        )
        if document is not None
    ]
    isin_codes = [
        str(code.get("code") or "").strip().upper()
        for code in raw.get("isinCodes")
        if isinstance(code, Mapping)
        and str(code.get("code") or "").strip()
    ]
    return {
        "external_id": external_id,
        "company": company,
        "company_number": str(raw.get("companyNumber") or "").strip(),
        "nationality": str(raw.get("nationality") or "").strip(),
        "title": title,
        "document_type": topic or "disclosure",
        "published": published,
        "received": _parse_datetime(str(raw.get("dateReceived") or ""))
        or published,
        "lei": str(raw.get("lei") or "").strip(),
        "isin_codes": isin_codes,
        "main_documents": documents,
        "attachments": attachments,
        "raw": dict(raw),
        "published_at_raw": str(raw.get("datePublication") or ""),
    }


def _parse_document(document: Mapping[str, Any]) -> Optional[Mapping[str, Any]]:
    file_data_id = str(document.get("fileDataId") or "").strip()
    if not file_data_id:
        return None
    return {
        "file_data_id": file_data_id,
        "language": str(document.get("language") or "").strip(),
        "title": str(document.get("title") or "").strip()
        or str(document.get("originalFileName") or "").strip(),
        "original_file_name": str(
            document.get("originalFileName") or ""
        ).strip(),
        "size": document.get("size"),
        "file_type": str(document.get("fileType") or "").strip(),
    }


def _parse_datetime(value: str) -> Optional[datetime]:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        # STORI timestamps without an offset are Brussels-local times.
        parsed = parsed.replace(tzinfo=BRUSSELS)
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
