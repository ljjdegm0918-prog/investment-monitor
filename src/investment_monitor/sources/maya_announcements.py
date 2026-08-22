# -*- coding: utf-8 -*-
"""MAYA / TASE official company disclosure API."""

from __future__ import annotations

import time
from datetime import date, datetime
from typing import Any, Callable, Iterable, Mapping, Optional, Sequence, Tuple
from urllib.parse import urlencode, urljoin
from zoneinfo import ZoneInfo

from ..models import MARKET_IL
from ..universe.il_universe import il_universe_name_map
from ..web_repository import normalize_il_ticker
from ._public_disclosure import PublicDisclosureConnector, PublicDisclosureError, fetch_json

BASE_URL = "https://maya.tase.co.il"
FILES_URL = "https://mayafiles.tase.co.il/"
AUTOCOMPLETE_URL = BASE_URL + "/api/v1/companies/autocomplete"
REPORTS_URL = BASE_URL + "/api/v1/reports/companies"
HEADERS = {
    "Accept": "application/json",
    "Accept-Language": "en-US",
    "Origin": BASE_URL,
    "Referer": BASE_URL + "/en/reports/companies",
}
REPORT_HEADERS = {**HEADERS, "Accept-Language": "he-IL"}


class MayaClient:
    timezone = ZoneInfo("Asia/Jerusalem")
    page_size = 30

    def __init__(
        self,
        *,
        sleeper: Callable[[float], None] = time.sleep,
        request_interval: float = 0.1,
    ) -> None:
        # Autocomplete is keyed to MAYA's company directory rather than the
        # tradeable-symbol universe.  Do not make one renamed/delisted or
        # otherwise unresolved symbol discard the other requested issuers.
        self.last_ticker_errors: Tuple[Tuple[str, str], ...] = ()
        self._sleeper = sleeper
        self.request_interval = max(0.0, request_interval)
        self._request_count = 0

    def _throttle(self) -> None:
        if self._request_count and self.request_interval:
            self._sleeper(self.request_interval)
        self._request_count += 1

    def fetch_for_tickers(
        self, tickers: Sequence[str], start_date: date, end_date: date
    ) -> Iterable[Mapping[str, Any]]:
        ticker_errors = []
        self._request_count = 0
        for ticker in tickers:
            company_id = self._company_id(ticker)
            if company_id is None:
                ticker_errors.append((ticker, "MAYA company not found"))
                continue
            offset = 0
            expected_total: Optional[int] = None
            seen_report_ids = set()
            while expected_total is None or offset < expected_total:
                self._throttle()
                payload, headers = fetch_json(
                    REPORTS_URL,
                    payload={
                        "companyId": company_id,
                        "fromDate": f"{start_date.isoformat()}T00:00:00.000Z",
                        "toDate": f"{end_date.isoformat()}T23:59:59.999Z",
                        "limit": self.page_size,
                        "offset": offset,
                    },
                    headers=REPORT_HEADERS,
                )
                if not isinstance(payload, list):
                    raise PublicDisclosureError("MAYA reports response is not a list")
                total = self._response_total(headers)
                if expected_total is None:
                    expected_total = total
                elif total != expected_total:
                    raise PublicDisclosureError(
                        "MAYA report pagination total changed during collection"
                    )
                remaining = expected_total - offset
                if remaining < 0 or len(payload) > self.page_size:
                    raise PublicDisclosureError("MAYA report pagination is invalid")
                if remaining == 0:
                    if payload:
                        raise PublicDisclosureError("MAYA returned records past x-total-count")
                    break
                if not payload or len(payload) != min(self.page_size, remaining):
                    raise PublicDisclosureError(
                        "MAYA report page does not match x-total-count"
                    )
                for record in payload:
                    if not isinstance(record, Mapping):
                        raise PublicDisclosureError("MAYA report row is not an object")
                    report_id = self._required_id(record, "id")
                    if report_id in seen_report_ids:
                        raise PublicDisclosureError(
                            f"MAYA report pagination repeated id {report_id}"
                        )
                    seen_report_ids.add(report_id)
                    raw_time = self._required_text(record, "publishDate")
                    published = self._published_at(raw_time)
                    companies = record.get("companies")
                    if not isinstance(companies, list):
                        raise PublicDisclosureError("MAYA report has no companies list")
                    company = next(
                        (
                            item for item in companies
                            if isinstance(item, Mapping) and item.get("companyId") == company_id
                        ),
                        None,
                    )
                    if not isinstance(company, Mapping):
                        raise PublicDisclosureError(
                            f"MAYA report {report_id} does not match company {company_id}"
                        )
                    attachments = self._attachments(record, report_id)
                    yield {
                        "external_id": f"maya:{report_id}",
                        "ticker": ticker,
                        "issuer": str(company.get("name") or ticker),
                        "published_at": published,
                        "published_at_raw": raw_time,
                        "published_timezone": "Asia/Jerusalem",
                        "title": str(record.get("title") or "Untitled disclosure"),
                        "document_type": record.get("formId") or "company disclosure",
                        "classification_code": record.get("formId"),
                        "url": attachments[0] if attachments else f"{BASE_URL}/en/reports/companies/{report_id}",
                        "attachments": attachments,
                        "retrieval_url": REPORTS_URL,
                        "raw_payload": record,
                        "raw_payload_format": "json",
                        "revision_semantics": (
                            f"correctives={record.get('correctives')!r}"
                        ),
                    }
                offset += len(payload)
        self.last_ticker_errors = tuple(ticker_errors)

    @staticmethod
    def _required_text(record: Mapping[str, Any], field: str) -> str:
        value = str(record.get(field) or "").strip()
        if not value:
            raise PublicDisclosureError(f"MAYA report is missing {field}")
        return value

    @classmethod
    def _required_id(cls, record: Mapping[str, Any], field: str) -> str:
        return cls._required_text(record, field)

    @staticmethod
    def _response_total(headers: Mapping[str, str]) -> int:
        value = next(
            (value for key, value in headers.items() if key.lower() == "x-total-count"),
            None,
        )
        try:
            total = int(str(value))
        except (TypeError, ValueError):
            raise PublicDisclosureError("MAYA response is missing a valid x-total-count") from None
        if total < 0:
            raise PublicDisclosureError("MAYA x-total-count cannot be negative")
        return total

    def _published_at(self, value: str) -> datetime:
        normalized = value.replace("Z", "+00:00")
        try:
            published = datetime.fromisoformat(normalized)
        except ValueError:
            # Python 3.9's ``fromisoformat`` rejects MAYA's two-digit
            # fractional seconds (for example ``.36``), though they are
            # valid ISO-8601 values emitted by the live endpoint.
            published = None
            for pattern in (
                "%Y-%m-%dT%H:%M:%S.%f%z",
                "%Y-%m-%dT%H:%M:%S.%f",
            ):
                try:
                    published = datetime.strptime(normalized, pattern)
                    break
                except ValueError:
                    pass
            if published is None:
                raise PublicDisclosureError(f"MAYA has invalid publishDate {value!r}")
        assert published is not None
        if published.tzinfo is None:
            # MAYA's observed company-report ``publishDate`` values are local
            # exchange timestamps without an offset.
            return published.replace(tzinfo=self.timezone)
        return published.astimezone(self.timezone)

    def _attachments(self, record: Mapping[str, Any], report_id: str) -> list[str]:
        rows = record.get("attachments")
        if rows is None:
            return []
        if not isinstance(rows, list):
            raise PublicDisclosureError(f"MAYA report {report_id} has invalid attachments")
        parsed = []
        for row in rows:
            if not isinstance(row, Mapping):
                raise PublicDisclosureError(f"MAYA report {report_id} has invalid attachment")
            path = str(row.get("url") or "").strip()
            if not path:
                raise PublicDisclosureError(f"MAYA report {report_id} attachment has no URL")
            parsed.append((str(row.get("fileType") or "").lower(), urljoin(FILES_URL, path)))
        # The list commonly places HTML before PDF.  Prefer the filing PDF for
        # the primary record URL but preserve every canonical MAYA file URL.
        parsed.sort(key=lambda attachment: (not attachment[0].startswith("pdf"), attachment[1]))
        return [url for _, url in parsed]

    def _company_id(self, ticker: str) -> Optional[int]:
        self._throttle()
        payload, _ = fetch_json(
            AUTOCOMPLETE_URL + "?" + urlencode({"search": ticker, "take": 20}),
            headers=HEADERS,
        )
        if not isinstance(payload, list):
            raise PublicDisclosureError("MAYA autocomplete response is not a list")
        upper = ticker.upper()
        exact = [
            item for item in payload
            if isinstance(item, Mapping)
            and str(item.get("type") or "").upper() == "COMPANY"
            and (
                str(item.get("label") or "").upper().split(" ", 1)[0] == upper
                or str(item.get("value") or "").upper().startswith(upper + "-")
                or str(item.get("value") or "").upper() == upper
            )
        ]
        if len(exact) != 1:
            return None
        try:
            return int(exact[0]["key"])
        except (KeyError, TypeError, ValueError):
            return None


class MayaAnnouncementsConnector(PublicDisclosureConnector):
    name = "maya_announcements"
    provider = "MAYA (TASE)"
    coverage_level = "official_company_api"

    def __init__(self, client: Optional[Any] = None, universe: Optional[Mapping[str, Mapping[str, str]]] = None) -> None:
        super().__init__(client=client or MayaClient(), universe=universe if universe is not None else il_universe_name_map(), normalizer=normalize_il_ticker, market=MARKET_IL)


__all__ = ["MayaAnnouncementsConnector", "MayaClient"]
