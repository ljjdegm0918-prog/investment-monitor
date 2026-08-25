"""Key-free FINRA OTC Security Master and Daily List client.

FINRA's public OTC Equities web application reads these datasets from the
public Query API.  The security master is a dated active-symbol snapshot; the
Daily List contains additions, deletions, symbol/name changes, bankruptcy,
dividends, splits and other corporate actions.  Both expose explicit date
partitions and ``record-total`` pagination headers.
"""

from __future__ import annotations

from datetime import date, datetime
import json
import os
import threading
import time
from typing import Any, Callable, Dict, List, Mapping, Optional, Sequence, Tuple
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

API_ROOT = "https://api.finra.org"
SECURITY_MASTER_DATASET = "otcSecurityMaster"
DAILY_LIST_DATASET = "otcDailyList"
DEFAULT_PAGE_SIZE = 5000
DEFAULT_MAX_PAGES = 10
RETRYABLE_STATUS_CODES = frozenset({429, 500, 502, 503, 504})

SECURITY_MASTER_FIELDS = (
    "issueSymbolIdentifier",
    "securityDescription",
    "issueType",
    "asOfDate",
)
DAILY_LIST_FIELDS = (
    "calendarDay",
    "dailyListDatetime",
    "dailyListReasonDescription",
    "newSymbolCode",
    "oldSymbolCode",
    "newSecurityDescription",
    "oldSecurityDescription",
    "exDate",
    "commentText",
    "newMarketCategoryCode",
    "oldMarketCategoryCode",
    "newFinancialStatusCode",
    "oldFinancialStatusCode",
    "subjectCorporateActionCode",
    "forwardSplitRate",
    "reverseSplitRate",
    "dividendTypeCode",
    "stockPercentage",
    "cashAmountText",
    "declarationDate",
    "recordDate",
    "paymentDate",
    "paymentMethodCode",
    "qualifiedDividendDescription",
)


class FinraOtcError(RuntimeError):
    """Base error for the public FINRA OTC datasets."""


class FinraOtcRequestError(FinraOtcError):
    """The FINRA public endpoint could not be read."""


class FinraOtcDataError(FinraOtcError):
    """The FINRA response was incomplete or changed contract."""


class FinraOtcClient:
    """Bounded, retrying client with strict partition/page reconciliation."""

    def __init__(
        self,
        *,
        opener: Callable[..., Any] = urlopen,
        timeout: float = 30.0,
        max_retries: int = 1,
        requests_per_second: float = 2.0,
        user_agent: str = "InvestmentMonitor/0.1 (public FINRA OTC monitor)",
        clock: Callable[[], float] = time.monotonic,
        sleeper: Callable[[float], None] = time.sleep,
    ) -> None:
        if timeout <= 0 or max_retries < 0 or requests_per_second <= 0:
            raise ValueError("FINRA OTC client limits are invalid")
        self._opener = opener
        self._timeout = timeout
        self._max_retries = max_retries
        self._minimum_interval = 1.0 / requests_per_second
        self._user_agent = user_agent
        self._clock = clock
        self._sleeper = sleeper
        self._last_request_at: Optional[float] = None
        self._lock = threading.Lock()
        self.last_security_master_total = 0
        self.last_daily_list_total = 0
        self.last_partition_dates: Tuple[str, ...] = ()

    @classmethod
    def from_environment(cls) -> "FinraOtcClient":
        return cls(
            timeout=float(os.environ.get("FINRA_OTC_TIMEOUT_SECONDS", "30")),
            max_retries=int(os.environ.get("FINRA_OTC_MAX_RETRIES", "1")),
            requests_per_second=float(
                os.environ.get("FINRA_OTC_REQUESTS_PER_SECOND", "2")
            ),
        )

    def fetch_active_security_master(
        self,
        *,
        page_size: int = DEFAULT_PAGE_SIZE,
        max_pages: int = DEFAULT_MAX_PAGES,
    ) -> Tuple[str, List[Mapping[str, Any]]]:
        partition = self.latest_partition(SECURITY_MASTER_DATASET, "asOfDate")
        rows = self._fetch_partition_pages(
            SECURITY_MASTER_DATASET,
            "asOfDate",
            partition,
            fields=SECURITY_MASTER_FIELDS,
            sort_fields=("+issueSymbolIdentifier",),
            page_size=page_size,
            max_pages=max_pages,
        )
        seen: set[str] = set()
        parsed: List[Mapping[str, Any]] = []
        for raw in rows:
            symbol = str(raw.get("issueSymbolIdentifier") or "").strip().upper()
            name = str(raw.get("securityDescription") or "").strip()
            issue_type = str(raw.get("issueType") or "").strip()
            as_of = str(raw.get("asOfDate") or "").strip()[:10]
            if not symbol or not name or not issue_type or as_of != partition:
                raise FinraOtcDataError(
                    "FINRA OTC Security Master row is incomplete or off-partition"
                )
            if symbol in seen:
                raise FinraOtcDataError(
                    f"FINRA OTC Security Master repeated symbol {symbol}"
                )
            seen.add(symbol)
            parsed.append(
                {
                    "ticker": symbol,
                    "name": name,
                    "issue_type": issue_type,
                    "as_of_date": partition,
                    "raw_payload": dict(raw),
                }
            )
        self.last_security_master_total = len(parsed)
        return partition, parsed

    def fetch_daily_list(
        self,
        start_date: date,
        end_date: date,
        *,
        page_size: int = DEFAULT_PAGE_SIZE,
        max_pages_per_day: int = DEFAULT_MAX_PAGES,
    ) -> List[Mapping[str, Any]]:
        if end_date < start_date:
            raise ValueError("end_date must not precede start_date")
        partitions = self.partitions(DAILY_LIST_DATASET, "calendarDay")
        if not partitions:
            raise FinraOtcDataError("FINRA OTC Daily List has no partitions")
        selected = tuple(
            value
            for value in partitions
            if start_date <= date.fromisoformat(value) <= end_date
        )
        records: List[Mapping[str, Any]] = []
        seen: set[str] = set()
        total = 0
        for partition in sorted(selected):
            rows = self._fetch_partition_pages(
                DAILY_LIST_DATASET,
                "calendarDay",
                partition,
                fields=DAILY_LIST_FIELDS,
                sort_fields=("-dailyListDatetime", "+newSymbolCode", "+oldSymbolCode"),
                page_size=page_size,
                max_pages=max_pages_per_day,
            )
            total += len(rows)
            for raw in rows:
                parsed = _parse_daily_list_row(raw, partition)
                identity = _daily_list_identity(parsed)
                if identity in seen:
                    raise FinraOtcDataError(
                        "FINRA OTC Daily List repeated a corporate-action row"
                    )
                seen.add(identity)
                records.append({**parsed, "row_identity": identity})
        self.last_partition_dates = selected
        self.last_daily_list_total = total
        return records

    def latest_partition(self, dataset: str, field: str) -> str:
        values = self.partitions(dataset, field)
        if not values:
            raise FinraOtcDataError(f"FINRA {dataset} has no date partitions")
        return max(values)

    def partitions(self, dataset: str, field: str) -> Tuple[str, ...]:
        url = f"{API_ROOT}/partitions/group/otcMarket/name/{dataset}"
        payload, _headers = self._request_json(Request(url, headers=self._headers()))
        if not isinstance(payload, Mapping):
            raise FinraOtcDataError(f"FINRA {dataset} partition root is invalid")
        group = str(payload.get("datasetGroup") or "").casefold()
        name = str(payload.get("datasetName") or "").casefold()
        fields = payload.get("partitionFields")
        available = payload.get("availablePartitions")
        if (
            group != "otcmarket"
            or name != dataset.casefold()
            or fields != [field]
            or not isinstance(available, list)
        ):
            raise FinraOtcDataError(f"FINRA {dataset} partition envelope changed")
        values: List[str] = []
        for entry in available:
            if not isinstance(entry, Mapping):
                raise FinraOtcDataError(f"FINRA {dataset} partition row is invalid")
            parts = entry.get("partitions")
            if not isinstance(parts, list) or len(parts) != 1:
                raise FinraOtcDataError(f"FINRA {dataset} partition row is invalid")
            value = str(parts[0] or "").strip()
            try:
                date.fromisoformat(value)
            except ValueError as error:
                raise FinraOtcDataError(
                    f"FINRA {dataset} partition date is invalid"
                ) from error
            values.append(value)
        if len(values) != len(set(values)):
            raise FinraOtcDataError(f"FINRA {dataset} repeated a partition")
        return tuple(values)

    def _fetch_partition_pages(
        self,
        dataset: str,
        partition_field: str,
        partition: str,
        *,
        fields: Sequence[str],
        sort_fields: Sequence[str],
        page_size: int,
        max_pages: int,
    ) -> List[Mapping[str, Any]]:
        if page_size <= 0 or page_size > 5000 or max_pages <= 0:
            raise ValueError("FINRA OTC pagination limits are invalid")
        url = f"{API_ROOT}/data/group/otcMarket/name/{dataset}"
        rows: List[Mapping[str, Any]] = []
        declared_total: Optional[int] = None
        for page in range(max_pages):
            offset = page * page_size
            body = {
                "fields": list(fields),
                "compareFilters": [
                    {
                        "fieldName": partition_field,
                        "fieldValue": partition,
                        "compareType": "EQUAL",
                    }
                ],
                "sortFields": list(sort_fields),
                "limit": page_size,
                "offset": offset,
                "delimiter": "|",
                "quoteValues": False,
            }
            request = Request(
                url,
                data=json.dumps(body, separators=(",", ":")).encode("utf-8"),
                headers={**self._headers(), "Content-Type": "application/json"},
                method="POST",
            )
            payload, headers = self._request_json(request)
            if not isinstance(payload, list) or any(
                not isinstance(row, Mapping) for row in payload
            ):
                raise FinraOtcDataError(f"FINRA {dataset} page is not a JSON list")
            total = _required_header_int(headers, "record-total")
            response_limit = _required_header_int(headers, "record-limit")
            response_offset = _required_header_int(headers, "record-offset")
            max_limit = _required_header_int(headers, "record-max-limit")
            if response_limit != page_size or response_offset != offset or max_limit < page_size:
                raise FinraOtcDataError(f"FINRA {dataset} pagination headers disagree")
            if declared_total is None:
                declared_total = total
                pages_required = max(1, (total + page_size - 1) // page_size)
                if pages_required > max_pages:
                    raise FinraOtcDataError(
                        f"FINRA {dataset} exceeds max_pages={max_pages}"
                    )
            elif total != declared_total:
                raise FinraOtcDataError(f"FINRA {dataset} record-total drifted")
            expected = max(0, min(page_size, total - offset))
            if len(payload) != expected:
                raise FinraOtcDataError(
                    f"FINRA {dataset} page length does not reconcile"
                )
            rows.extend(dict(row) for row in payload)
            if len(rows) >= total:
                break
        if declared_total is None or len(rows) != declared_total:
            raise FinraOtcDataError(f"FINRA {dataset} result count did not reconcile")
        return rows

    def _request_json(self, request: Request) -> Tuple[Any, Mapping[str, str]]:
        for attempt in range(self._max_retries + 1):
            self._wait()
            try:
                with self._opener(request, timeout=self._timeout) as response:
                    raw = response.read().decode("utf-8")
                    headers = {
                        str(key).casefold(): str(value)
                        for key, value in response.headers.items()
                    }
                return json.loads(raw), headers
            except HTTPError as error:
                if error.code not in RETRYABLE_STATUS_CODES or attempt == self._max_retries:
                    raise FinraOtcRequestError(
                        f"FINRA OTC request failed with HTTP {error.code}"
                    ) from error
            except (URLError, TimeoutError, OSError) as error:
                if attempt == self._max_retries:
                    raise FinraOtcRequestError(
                        "FINRA OTC request failed after retries"
                    ) from error
            except (UnicodeDecodeError, json.JSONDecodeError) as error:
                raise FinraOtcDataError("FINRA OTC returned non-JSON content") from error
            self._sleeper(0.5 * (2**attempt))
        raise FinraOtcRequestError("FINRA OTC request failed")

    def _headers(self) -> Dict[str, str]:
        return {"User-Agent": self._user_agent, "Accept": "application/json"}

    def _wait(self) -> None:
        with self._lock:
            now = self._clock()
            if self._last_request_at is not None:
                remaining = self._minimum_interval - (now - self._last_request_at)
                if remaining > 0:
                    self._sleeper(remaining)
                    now = self._clock()
            self._last_request_at = now


def _required_header_int(headers: Mapping[str, str], name: str) -> int:
    try:
        value = int(headers[name.casefold()])
    except (KeyError, TypeError, ValueError) as error:
        raise FinraOtcDataError(f"FINRA response is missing {name}") from error
    if value < 0:
        raise FinraOtcDataError(f"FINRA response has invalid {name}")
    return value


def _parse_daily_list_row(raw: Mapping[str, Any], partition: str) -> Mapping[str, Any]:
    timestamp = str(raw.get("dailyListDatetime") or "").strip()
    reason = str(raw.get("dailyListReasonDescription") or "").strip()
    old_symbol = str(raw.get("oldSymbolCode") or "").strip().upper()
    new_symbol = str(raw.get("newSymbolCode") or "").strip().upper()
    calendar_day = str(raw.get("calendarDay") or partition).strip()[:10]
    try:
        parsed_time = datetime.strptime(timestamp, "%Y-%m-%d %H:%M:%S.%f")
    except ValueError as error:
        raise FinraOtcDataError("FINRA OTC Daily List timestamp is invalid") from error
    if (
        not reason
        or not (old_symbol or new_symbol)
        or calendar_day != partition
        or parsed_time.date().isoformat() != partition
    ):
        raise FinraOtcDataError("FINRA OTC Daily List row is incomplete")
    return {
        **dict(raw),
        "calendarDay": partition,
        "dailyListDatetime": timestamp,
        "dailyListReasonDescription": reason,
        "oldSymbolCode": old_symbol or None,
        "newSymbolCode": new_symbol or None,
    }


def _daily_list_identity(row: Mapping[str, Any]) -> str:
    values = (
        row.get("dailyListDatetime"),
        row.get("dailyListReasonDescription"),
        row.get("oldSymbolCode"),
        row.get("newSymbolCode"),
        row.get("oldSecurityDescription"),
        row.get("newSecurityDescription"),
        row.get("exDate"),
        row.get("subjectCorporateActionCode"),
        row.get("cashAmountText"),
    )
    return "|".join(str(value or "").strip() for value in values)


__all__ = [
    "API_ROOT",
    "DAILY_LIST_DATASET",
    "DAILY_LIST_FIELDS",
    "DEFAULT_MAX_PAGES",
    "DEFAULT_PAGE_SIZE",
    "FinraOtcClient",
    "FinraOtcDataError",
    "FinraOtcError",
    "FinraOtcRequestError",
    "SECURITY_MASTER_DATASET",
    "SECURITY_MASTER_FIELDS",
]
