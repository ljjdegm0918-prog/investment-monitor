# -*- coding: utf-8 -*-
"""MOPS official historical material-disclosure connector for Taiwan.

The current MOPS Vue application calls the key-free JSON endpoints below.
The list endpoint is queried per company and calendar month; detail requests
add the official clause and full explanatory text.  This covers the MOPS
material-disclosure family, not every financial/governance document family.
"""

from __future__ import annotations

import json
import os
import time
from calendar import monthrange
from datetime import date, datetime, timezone
from typing import Any, Callable, Iterable, List, Mapping, Optional, Sequence, Tuple
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

from ..models import CollectionRequest, InformationItem, MARKET_TW
from ..provenance import build_raw_provenance
from ..web_repository import normalize_tw_ticker

BASE_URL = "https://mops.twse.com.tw"
LIST_URL = BASE_URL + "/mops/api/t05st01"
DETAIL_URL = BASE_URL + "/mops/api/t05st01_detail"
PUBLIC_PAGE = BASE_URL + "/mops/web/t05st01"
TAIPEI = ZoneInfo("Asia/Taipei")


class MopsDisclosureError(RuntimeError):
    """Base MOPS collection error."""


class MopsDisclosureRequestError(MopsDisclosureError):
    """MOPS request failed."""


class MopsDisclosureDataError(MopsDisclosureError):
    """MOPS returned an unexpected response."""


def _month_windows(start: date, end: date) -> Iterable[Tuple[date, date]]:
    current = start.replace(day=1)
    while current <= end:
        last = date(current.year, current.month, monthrange(current.year, current.month)[1])
        yield max(start, current), min(end, last)
        current = date(current.year + (current.month == 12), current.month % 12 + 1, 1)


class MopsDisclosureClient:
    """Small injectable client for the official MOPS JSON application API."""

    def __init__(
        self,
        *,
        opener: Callable[..., Any] = urlopen,
        timeout: float = 30.0,
        requests_per_second: float = 1.0,
        sleeper: Callable[[float], None] = time.sleep,
    ) -> None:
        if timeout <= 0 or requests_per_second <= 0:
            raise ValueError("MOPS timeout and request rate must be positive")
        self._opener = opener
        self._timeout = timeout
        self._minimum_interval = 1.0 / requests_per_second
        self._sleeper = sleeper
        self._last_request_at: Optional[float] = None

    @classmethod
    def from_environment(cls) -> "MopsDisclosureClient":
        return cls(
            timeout=float(os.environ.get("MOPS_DISCLOSURE_TIMEOUT_SECONDS", "30")),
            requests_per_second=float(
                os.environ.get("MOPS_DISCLOSURE_REQUESTS_PER_SECOND", "1")
            ),
        )

    def fetch_by_ticker(
        self, ticker: str, start_date: date, end_date: date
    ) -> List[Mapping[str, Any]]:
        records: List[Mapping[str, Any]] = []
        seen = set()
        for window_start, window_end in _month_windows(start_date, end_date):
            payload = self._post_json(LIST_URL, {
                "companyId": ticker,
                "year": str(window_start.year - 1911),
                "month": str(window_start.month),
                "firstDay": str(window_start.day),
                "lastDay": str(window_end.day),
            })
            result = _result_object(payload, "MOPS list")
            rows = result.get("data")
            if not isinstance(rows, list):
                raise MopsDisclosureDataError("MOPS list result.data is not a list")
            for row in rows:
                record = _parse_list_row(row, ticker=ticker)
                if record is None or record["external_id"] in seen:
                    continue
                seen.add(record["external_id"])
                detail_parameters = record["detail_parameters"]
                detail_payload = self._post_json(DETAIL_URL, detail_parameters)
                detail_result = _result_object(detail_payload, "MOPS detail")
                detail_rows = detail_result.get("data")
                if not isinstance(detail_rows, list) or not detail_rows:
                    raise MopsDisclosureDataError("MOPS detail result.data is empty")
                record.update(_parse_detail_row(detail_rows[0]))
                record["raw_payload"] = {"list": row, "detail": detail_rows[0]}
                records.append(record)
        return records

    def _post_json(self, url: str, payload: Mapping[str, Any]) -> Mapping[str, Any]:
        now = time.monotonic()
        if self._last_request_at is not None:
            remaining = self._minimum_interval - (now - self._last_request_at)
            if remaining > 0:
                self._sleeper(remaining)
        request = Request(
            url,
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers={
                "Accept": "application/json",
                "Content-Type": "application/json",
                "Origin": BASE_URL,
                "Referer": PUBLIC_PAGE,
                "User-Agent": "Mozilla/5.0 (compatible; InvestmentMonitor/0.1)",
            },
            method="POST",
        )
        try:
            with self._opener(request, timeout=self._timeout) as response:
                raw = response.read()
            self._last_request_at = time.monotonic()
            decoded = json.loads(raw.decode("utf-8", errors="replace"))
        except HTTPError as error:
            raise MopsDisclosureRequestError(
                f"MOPS request failed with HTTP {error.code}: {url}"
            ) from error
        except (URLError, TimeoutError, OSError) as error:
            raise MopsDisclosureRequestError(f"MOPS request failed: {url}: {error}") from error
        except (json.JSONDecodeError, UnicodeDecodeError) as error:
            raise MopsDisclosureDataError("MOPS response was not valid JSON") from error
        if not isinstance(decoded, Mapping):
            raise MopsDisclosureDataError("MOPS response is not an object")
        return decoded


def _result_object(payload: Mapping[str, Any], label: str) -> Mapping[str, Any]:
    if payload.get("code") != 200 or payload.get("message") != "查詢成功":
        raise MopsDisclosureDataError(
            f"{label} failed: code={payload.get('code')!r} message={payload.get('message')!r}"
        )
    result = payload.get("result")
    if not isinstance(result, Mapping):
        raise MopsDisclosureDataError(f"{label} result is not an object")
    return result


def _parse_roc_date(value: str) -> date:
    parts = str(value).strip().replace("-", "/").split("/")
    if len(parts) != 3:
        raise MopsDisclosureDataError(f"invalid MOPS ROC date: {value!r}")
    try:
        return date(int(parts[0]) + 1911, int(parts[1]), int(parts[2]))
    except ValueError as error:
        raise MopsDisclosureDataError(f"invalid MOPS ROC date: {value!r}") from error


def _parse_list_row(row: Any, *, ticker: str) -> Optional[dict[str, Any]]:
    if not isinstance(row, list) or len(row) < 6:
        raise MopsDisclosureDataError("MOPS list row has an unexpected shape")
    detail = row[5]
    if not isinstance(detail, Mapping) or detail.get("apiName") != "t05st01_detail":
        raise MopsDisclosureDataError("MOPS list row has no official detail parameters")
    parameters = detail.get("parameters")
    if not isinstance(parameters, Mapping):
        raise MopsDisclosureDataError("MOPS detail parameters are invalid")
    parameter_ticker = normalize_tw_ticker(str(parameters.get("companyId") or ""))
    if parameter_ticker != ticker:
        raise MopsDisclosureDataError(
            "MOPS detail companyId did not match the requested ticker"
        )
    day = _parse_roc_date(str(row[2]))
    try:
        published = datetime.strptime(
            f"{day.isoformat()} {str(row[3]).strip()}", "%Y-%m-%d %H:%M:%S"
        ).replace(tzinfo=TAIPEI)
    except ValueError as error:
        raise MopsDisclosureDataError("MOPS list time is invalid") from error
    market_kind = str(parameters.get("marketKind") or "")
    serial = str(parameters.get("serialNumber") or "")
    enter_date = str(parameters.get("enterDate") or "")
    if not market_kind or not serial or not enter_date:
        raise MopsDisclosureDataError("MOPS detail identity is incomplete")
    return {
        "external_id": f"mops:{market_kind}:{ticker}:{enter_date}:{serial}",
        "ticker": ticker,
        "issuer": str(row[1]).strip() or ticker,
        "published_at": published,
        "published_at_raw": f"{row[2]} {row[3]}",
        "title": str(row[4]).strip(),
        "detail_parameters": dict(parameters),
        "market_kind": market_kind,
        "serial_number": serial,
        "enter_date": enter_date,
    }


def _parse_detail_row(row: Any) -> Mapping[str, Any]:
    if not isinstance(row, list) or len(row) < 10:
        raise MopsDisclosureDataError("MOPS detail row has an unexpected shape")
    return {
        "speaker": str(row[3]).strip(),
        "speaker_title": str(row[4]).strip(),
        "title": str(row[6]).strip(),
        "classification": str(row[7]).strip(),
        "event_date_raw": str(row[8]).strip(),
        "summary": str(row[9]).strip(),
    }


class MopsDisclosureConnector:
    name = "mops_disclosures"
    provider = "MOPS (TWSE) historical material disclosures"
    max_lookback_days = 30
    coverage_level = "official_material_disclosures"

    def __init__(self, client: Optional[MopsDisclosureClient] = None) -> None:
        self._client = client or MopsDisclosureClient.from_environment()
        self._last_errors: Tuple[Tuple[str, str], ...] = ()
        self.last_collection_status = "empty"

    @property
    def last_errors(self) -> Tuple[Tuple[str, str], ...]:
        return self._last_errors

    def collect(self, request: CollectionRequest) -> List[InformationItem]:
        tickers = tuple(dict.fromkeys(
            normalize_tw_ticker(ticker)
            for ticker in request.tickers
            if request.market_for(ticker) == MARKET_TW
        ))
        if not tickers:
            self._last_errors = ()
            self.last_collection_status = "empty"
            return []
        items: List[InformationItem] = []
        failures: List[Tuple[str, str]] = []
        collected_at = datetime.now(timezone.utc)
        for ticker in tickers:
            try:
                records = self._client.fetch_by_ticker(
                    ticker, request.start_date, request.end_date
                )
            except Exception as error:
                failures.append((ticker, str(error) or error.__class__.__name__))
                if len(tickers) == 1:
                    self._last_errors = tuple(failures)
                    self.last_collection_status = "failure"
                    raise MopsDisclosureRequestError(failures[0][1]) from error
                continue
            for record in records:
                published = record["published_at"]
                if not request.start_date <= published.date() <= request.end_date:
                    continue
                raw = record["raw_payload"]
                items.append(InformationItem(
                    source=self.name,
                    source_type="regulatory_filing",
                    external_id=str(record["external_id"]),
                    tickers=(ticker,),
                    issuer=str(record["issuer"]),
                    published_at=published,
                    title=str(record["title"]),
                    document_type=str(record["classification"] or "material_disclosure"),
                    url=PUBLIC_PAGE,
                    collected_at=collected_at,
                    raw_metadata={
                        **build_raw_provenance(
                            official_source_id=str(record["external_id"]),
                            official_source_url=PUBLIC_PAGE,
                            retrieval_url=LIST_URL,
                            raw_payload=raw,
                            raw_payload_format="json",
                            classification_code=str(record["classification"]),
                            classification_label="MOPS material disclosure",
                            published_at_raw=str(record["published_at_raw"]),
                            published_timezone="Asia/Taipei",
                        ),
                        "provider": "mops_twse",
                        "coverage_level": self.coverage_level,
                        "market_kind": record["market_kind"],
                        "serial_number": record["serial_number"],
                        "enter_date": record["enter_date"],
                        "detail_parameters": record["detail_parameters"],
                        "speaker": record["speaker"],
                        "speaker_title": record["speaker_title"],
                        "event_date_raw": record["event_date_raw"],
                    },
                    market=MARKET_TW,
                    summary=str(record["summary"] or "") or None,
                    effective_at=published,
                ))
        self._last_errors = tuple(failures)
        self.last_collection_status = (
            "partial" if failures and items else "failure" if failures else
            "success" if items else "empty"
        )
        return items


__all__ = [
    "MopsDisclosureClient",
    "MopsDisclosureConnector",
    "MopsDisclosureDataError",
    "MopsDisclosureError",
    "MopsDisclosureRequestError",
]
