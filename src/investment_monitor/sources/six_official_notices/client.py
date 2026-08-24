"""Key-free SIX Exchange Regulation official-notices client.

The public SIX/SER Official Notices pages use the ``sheldon`` JSON service
and publish an RSS link.  This client uses the JSON list because it exposes a
declared total and zero-based pagination, then resolves details only for ISINs
requested by the caller.  That keeps daily scans bounded and prevents the
large structured-product stream from being misclassified as equity filings.
"""

from __future__ import annotations

from datetime import date, datetime
from math import ceil
import json
import os
import re
import threading
import time
from typing import Any, Callable, Dict, List, Mapping, Optional, Sequence
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

LIST_URL = "https://www.ser-ag.com/sheldon/official_notices/v2/find.json"
DETAIL_URL = (
    "https://www.ser-ag.com/sheldon/official_notices/v2/details/{notice_id}.json"
)
PUBLIC_URL = (
    "https://www.ser-ag.com/en/resources/notifications-market-participants/"
    "official-notices.html#notificationId={notice_id}"
)
RSS_URL = "https://www.ser-ag.com/itf-data/official-notices/rss-en.xml"
DEFAULT_PAGE_SIZE = 500
DEFAULT_MAX_PAGES = 100
RETRYABLE_STATUS_CODES = frozenset({429, 500, 502, 503, 504})
ZURICH = ZoneInfo("Europe/Zurich")
_ISIN = re.compile(r"(?<![A-Z0-9])[A-Z]{2}[A-Z0-9]{10}(?![A-Z0-9])")


class SixOfficialNoticesError(RuntimeError):
    """Base error for the official-notices connector."""


class SixOfficialNoticesRequestError(SixOfficialNoticesError):
    """The public endpoint could not be read."""


class SixOfficialNoticesDataError(SixOfficialNoticesError):
    """The public endpoint returned an incomplete or changed contract."""


class SixOfficialNoticesClient:
    """Bounded client for the public SIX/SER list and detail JSON."""

    timezone = ZURICH

    def __init__(
        self,
        *,
        opener: Callable[..., Any] = urlopen,
        timeout: float = 20.0,
        max_retries: int = 1,
        requests_per_second: float = 1.0,
        user_agent: str = "InvestmentMonitor/0.1 (internal SIX notice monitor)",
        clock: Callable[[], float] = time.monotonic,
        sleeper: Callable[[float], None] = time.sleep,
    ) -> None:
        if timeout <= 0 or max_retries < 0 or requests_per_second <= 0:
            raise ValueError("SIX Official Notices client limits are invalid")
        self._opener = opener
        self._timeout = timeout
        self._max_retries = max_retries
        self._minimum_interval = 1.0 / requests_per_second
        self._user_agent = user_agent
        self._clock = clock
        self._sleeper = sleeper
        self._last_request_at: Optional[float] = None
        self._lock = threading.Lock()
        self.last_list_records = 0
        self.last_matched_records = 0

    @classmethod
    def from_environment(cls) -> "SixOfficialNoticesClient":
        return cls(
            timeout=float(os.environ.get("SIX_NOTICES_TIMEOUT_SECONDS", "20")),
            max_retries=int(os.environ.get("SIX_NOTICES_MAX_RETRIES", "1")),
            requests_per_second=float(
                os.environ.get("SIX_NOTICES_REQUESTS_PER_SECOND", "1")
            ),
        )

    def fetch_for_isins(
        self,
        isins: Sequence[str],
        start_date: date,
        end_date: date,
        *,
        page_size: int = DEFAULT_PAGE_SIZE,
        max_pages: int = DEFAULT_MAX_PAGES,
    ) -> List[Mapping[str, Any]]:
        if end_date < start_date:
            raise ValueError("end_date must not precede start_date")
        if page_size <= 0 or max_pages <= 0:
            raise ValueError("SIX Official Notices page limits must be positive")
        targets = {
            str(value or "").strip().upper()
            for value in isins
            if _ISIN.fullmatch(str(value or "").strip().upper())
        }
        if not targets:
            self.last_list_records = 0
            self.last_matched_records = 0
            return []

        matched: List[Mapping[str, Any]] = []
        seen_ids: set[int] = set()
        declared_total: Optional[int] = None
        pages_required: Optional[int] = None
        for page in range(max_pages):
            params = {
                "firstDate": start_date.strftime("%Y%m%d"),
                "lastDate": end_date.strftime("%Y%m%d"),
                "pageNumber": str(page),
                "pageSize": str(page_size),
                "sortAttribute": "dateTime",
                "sortDirection": "desc",
            }
            retrieval_url = LIST_URL + "?" + urlencode(params)
            payload = self._get_json(retrieval_url)
            total, rows = _parse_list_envelope(payload)
            if declared_total is None:
                declared_total = total
                pages_required = ceil(total / page_size) if total else 1
                if pages_required > max_pages:
                    raise SixOfficialNoticesDataError(
                        "SIX Official Notices result exceeds "
                        f"max_pages={max_pages}"
                    )
            elif total != declared_total:
                raise SixOfficialNoticesDataError(
                    "SIX Official Notices totalCount drifted between pages"
                )
            expected = max(0, min(page_size, total - page * page_size))
            if len(rows) != expected:
                raise SixOfficialNoticesDataError(
                    "SIX Official Notices page length does not match totalCount"
                )
            for raw in rows:
                row = _parse_list_row(raw)
                notice_id = int(row["notice_id"])
                if notice_id in seen_ids:
                    raise SixOfficialNoticesDataError(
                        "SIX Official Notices repeated a noticeId across pages"
                    )
                seen_ids.add(notice_id)
                matched_isins = tuple(
                    sorted(set(row["isins"]) & targets)
                )
                if matched_isins:
                    matched.append(
                        {
                            **row,
                            "matched_isins": matched_isins,
                            "list_retrieval_url": retrieval_url,
                        }
                    )
            if pages_required is not None and page + 1 >= pages_required:
                break
        if declared_total is None or len(seen_ids) != declared_total:
            raise SixOfficialNoticesDataError(
                "SIX Official Notices result count did not reconcile"
            )

        self.last_list_records = declared_total
        records = [self._fetch_detail(row) for row in matched]
        self.last_matched_records = len(records)
        return records

    def _fetch_detail(self, summary: Mapping[str, Any]) -> Mapping[str, Any]:
        notice_id = int(summary["notice_id"])
        detail_url = DETAIL_URL.format(notice_id=notice_id)
        payload = self._get_json(detail_url)
        detail = _parse_detail_envelope(payload, notice_id)
        for field in ("contact", "title", "notice_type", "date"):
            if detail[field] != summary[field]:
                raise SixOfficialNoticesDataError(
                    f"SIX Official Notice {notice_id} detail disagrees on {field}"
                )
        if set(detail["isins"]) != set(summary["isins"]):
            raise SixOfficialNoticesDataError(
                f"SIX Official Notice {notice_id} detail disagrees on ISINs"
            )
        published_at = _published_at(int(summary["date"]), int(summary["publish_time"]))
        public_url = PUBLIC_URL.format(notice_id=notice_id)
        return {
            "external_id": f"six-notice:{notice_id}",
            "notice_id": notice_id,
            "official_notice_number": detail["number"],
            "isin": (
                summary["matched_isins"][0]
                if len(summary["matched_isins"]) == 1
                else None
            ),
            "isins": list(summary["isins"]),
            "matched_isins": list(summary["matched_isins"]),
            "isin_raw": summary["isin_raw"],
            "issuer": summary["contact"],
            "published_at": published_at,
            "published_at_raw": (
                f"{int(summary['date']):08d} {int(summary['publish_time']):06d}"
            ),
            "published_timezone": "Europe/Zurich",
            "title": summary["title"],
            "document_type": f"SIX Official Notice ({summary['notice_type']})",
            "classification_code": summary["notice_type"],
            "url": public_url,
            "retrieval_url": detail_url,
            "list_retrieval_url": summary["list_retrieval_url"],
            "valor_number": detail["valor_number"],
            "summary": detail["text"] or None,
            "raw_payload": {
                "list": summary["raw_payload"],
                "detail": detail["raw_payload"],
            },
            "raw_payload_format": "json",
            "attachments": [],
        }

    def _get_json(self, url: str) -> Mapping[str, Any]:
        for attempt in range(self._max_retries + 1):
            self._wait()
            request = Request(
                url,
                headers={
                    "User-Agent": self._user_agent,
                    "Accept": "application/json",
                    "Referer": (
                        "https://www.ser-ag.com/en/resources/"
                        "notifications-market-participants/official-notices.html"
                    ),
                },
            )
            try:
                with self._opener(request, timeout=self._timeout) as response:
                    raw = response.read().decode("utf-8")
                payload = json.loads(raw)
                if not isinstance(payload, Mapping):
                    raise SixOfficialNoticesDataError(
                        "SIX Official Notices JSON root is not an object"
                    )
                return payload
            except HTTPError as error:
                if (
                    error.code not in RETRYABLE_STATUS_CODES
                    or attempt == self._max_retries
                ):
                    raise SixOfficialNoticesRequestError(
                        f"SIX Official Notices request failed with HTTP {error.code}"
                    ) from error
            except (URLError, TimeoutError, OSError) as error:
                if attempt == self._max_retries:
                    raise SixOfficialNoticesRequestError(
                        "SIX Official Notices request failed after retries"
                    ) from error
            except (UnicodeDecodeError, json.JSONDecodeError) as error:
                raise SixOfficialNoticesDataError(
                    "SIX Official Notices returned non-JSON content"
                ) from error
            self._sleeper(0.5 * (2**attempt))
        raise SixOfficialNoticesRequestError("SIX Official Notices request failed")

    def _wait(self) -> None:
        with self._lock:
            now = self._clock()
            if self._last_request_at is not None:
                remaining = self._minimum_interval - (now - self._last_request_at)
                if remaining > 0:
                    self._sleeper(remaining)
                    now = self._clock()
            self._last_request_at = now


def _parse_list_envelope(
    payload: Mapping[str, Any],
) -> tuple[int, Sequence[Mapping[str, Any]]]:
    if payload.get("status") != "Ok":
        raise SixOfficialNoticesDataError(
            "SIX Official Notices response status is not Ok"
        )
    total = payload.get("totalCount")
    rows = payload.get("itemList")
    if not isinstance(total, int) or total < 0 or not isinstance(rows, list):
        raise SixOfficialNoticesDataError(
            "SIX Official Notices pagination envelope is invalid"
        )
    if any(not isinstance(row, Mapping) for row in rows):
        raise SixOfficialNoticesDataError(
            "SIX Official Notices itemList contains an invalid row"
        )
    return total, rows


def _parse_list_row(raw: Mapping[str, Any]) -> Mapping[str, Any]:
    try:
        notice_id = int(raw["noticeId"])
        raw_date = int(raw["date"])
        publish_time = int(raw["publishTime"])
    except (KeyError, TypeError, ValueError) as error:
        raise SixOfficialNoticesDataError(
            "SIX Official Notices row identity or timestamp is invalid"
        ) from error
    notice_type = str(raw.get("noticeType") or "").strip()
    contact = str(raw.get("contact") or "").strip()
    title = str(raw.get("title") or "").strip()
    isin_raw = str(raw.get("isin") or "").strip()
    isins = tuple(dict.fromkeys(_ISIN.findall(isin_raw.upper())))
    if (
        notice_id <= 0
        or not notice_type
        or not contact
        or not title
        or not _valid_date_time(raw_date, publish_time)
    ):
        raise SixOfficialNoticesDataError(
            "SIX Official Notices row is missing required fields"
        )
    return {
        "notice_id": notice_id,
        "date": raw_date,
        "publish_time": publish_time,
        "notice_type": notice_type,
        "contact": contact,
        "title": title,
        "isin": isins[0] if len(isins) == 1 else None,
        "isins": isins,
        "isin_raw": isin_raw or None,
        "raw_payload": dict(raw),
    }


def _parse_detail_envelope(
    payload: Mapping[str, Any], notice_id: int
) -> Mapping[str, Any]:
    if payload.get("status") != "Ok" or payload.get("totalCount") != 1:
        raise SixOfficialNoticesDataError(
            f"SIX Official Notice {notice_id} detail envelope is invalid"
        )
    rows = payload.get("itemList")
    if not isinstance(rows, list) or len(rows) != 1 or not isinstance(rows[0], Mapping):
        raise SixOfficialNoticesDataError(
            f"SIX Official Notice {notice_id} detail row is invalid"
        )
    raw = rows[0]
    try:
        returned_id = int(raw["noticeId"])
        number = int(raw["number"])
        raw_date = int(raw["date"])
    except (KeyError, TypeError, ValueError) as error:
        raise SixOfficialNoticesDataError(
            f"SIX Official Notice {notice_id} detail identity is invalid"
        ) from error
    notice_type = str(raw.get("noticeType") or "").strip()
    contact = str(raw.get("contact") or "").strip()
    title = str(raw.get("title") or "").strip()
    text = str(raw.get("text") or "").strip()
    isin_raw = str(raw.get("isin") or "").strip()
    isins = tuple(dict.fromkeys(_ISIN.findall(isin_raw.upper())))
    valor = raw.get("valorNumber")
    if returned_id != notice_id:
        raise SixOfficialNoticesDataError(
            f"SIX Official Notice {notice_id} detail identity does not match"
        )
    if (
        number <= 0
        or not notice_type
        or not contact
        or not title
        or not text
        or (valor is not None and not str(valor).strip())
    ):
        raise SixOfficialNoticesDataError(
            f"SIX Official Notice {notice_id} detail is incomplete"
        )
    return {
        "notice_id": returned_id,
        "number": number,
        "date": raw_date,
        "notice_type": notice_type,
        "contact": contact,
        "title": title,
        "text": text,
        "isin": isins[0] if len(isins) == 1 else None,
        "isins": isins,
        "isin_raw": isin_raw or None,
        "valor_number": str(valor).strip() if valor is not None else None,
        "raw_payload": dict(raw),
    }


def _valid_date_time(raw_date: int, raw_time: int) -> bool:
    try:
        _published_at(raw_date, raw_time)
    except SixOfficialNoticesDataError:
        return False
    return True


def _published_at(raw_date: int, raw_time: int) -> datetime:
    try:
        value = f"{int(raw_date):08d}{int(raw_time):06d}"
        return datetime.strptime(value, "%Y%m%d%H%M%S").replace(tzinfo=ZURICH)
    except (TypeError, ValueError) as error:
        raise SixOfficialNoticesDataError(
            "SIX Official Notices publication timestamp is invalid"
        ) from error


__all__ = [
    "DETAIL_URL",
    "LIST_URL",
    "PUBLIC_URL",
    "RSS_URL",
    "SixOfficialNoticesClient",
    "SixOfficialNoticesDataError",
    "SixOfficialNoticesError",
    "SixOfficialNoticesRequestError",
]
