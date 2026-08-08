"""Collect TDnet timely disclosures from the free JPX public pages.

The public HTML pages are the primary source.  Yanoshin is an independent,
unofficial cross-check only: records found there are never silently promoted
to official records.  A run fails closed when page completeness cannot be
proved or the cross-check finds records absent from the official parse.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from datetime import date, datetime, time as datetime_time, timedelta, timezone
from enum import Enum
from hashlib import sha256
from html.parser import HTMLParser
import json
import os
from pathlib import Path
import re
import threading
import time
from typing import Any, Callable, Dict, Iterable, List, Optional, Sequence, Set, Tuple
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qsl, urlencode, urljoin, urlsplit, urlunsplit
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

from ...connectors.base import ConnectorUnavailableError, SecretField
from ...models import CollectionRequest, InformationItem, MARKET_JP


OFFICIAL_BASE_URL = "https://www.release.tdnet.info/inbs/"
YANOSHIN_BASE_URL = "https://webapi.yanoshin.jp/webapi/tdnet/list/"
OFFICIAL_PAGE = "I_list_{page:03d}_{day}.html"
JAPAN_TIME = ZoneInfo("Asia/Tokyo")
RETRYABLE_STATUS_CODES = frozenset({429, 500, 502, 503, 504})
PAGE_LINK_PATTERN = re.compile(r"I_list_(\d{3})_(\d{8})\.html", re.I)
DECLARED_COUNT_PATTERNS = (
    re.compile(r"(?:全|合計)\s*([0-9][0-9,]*)\s*件"),
    re.compile(r"([0-9][0-9,]*)\s*件\s*(?:中|あります)"),
)
OFFICIAL_EMPTY_TEXT = "に開示された情報はありません。"
TIME_PATTERN = re.compile(r"(?:^|\s)([0-2]?\d):([0-5]\d)(?:\s|$)")
COMPANY_CODE_PATTERN = re.compile(r"(?:^|\s)([0-9A-Z]{4,5})(?:\s|$)", re.I)
TARGET_TICKER_PATTERN = re.compile(
    r"^(?P<code>[0-9]{4}|[0-9]{3}[A-Z])(?:\.T|:JP)?$",
    re.I,
)
DEFAULT_YANOSHIN_LIMIT = 2000
TDNET_USER_AGENT_HELP = (
    "Required identifier for this personal collector; review JPX public-page "
    "access terms before enabling automation."
)


class TDnetCollectionError(RuntimeError):
    """Raised when a TDnet run cannot establish complete source coverage."""


class TDnetDataError(TDnetCollectionError):
    """Raised when a TDnet response cannot be interpreted safely."""

    def __init__(
        self,
        message: str,
        *,
        crosscheck_reported_total: Optional[int] = None,
        crosscheck_coverage: Optional[str] = None,
    ) -> None:
        super().__init__(message)
        self.crosscheck_reported_total = crosscheck_reported_total
        self.crosscheck_coverage = crosscheck_coverage


class TDnetCompleteness(str, Enum):
    COMPLETE = "complete"
    PROVISIONAL = "provisional"
    PARTIAL = "partial"
    UNKNOWN = "unknown"
    STALE = "stale"
    RECONCILIATION_REQUIRED = "reconciliation_required"


@dataclass(frozen=True)
class RawDisclosure:
    company_code: str
    company_name: str
    published_local: datetime
    title: str
    document_url: str
    xbrl_url: Optional[str]
    page_url: str
    raw_cells: Tuple[str, ...]

    @property
    def comparison_key(self) -> Tuple[str, str, str]:
        return (
            _normalize_company_code(self.company_code),
            self.published_local.strftime("%Y-%m-%dT%H:%M"),
            _normalize_text(self.title),
        )


@dataclass(frozen=True)
class TDnetRunReport:
    day: date
    status: TDnetCompleteness
    declared_count: Optional[int]
    official_count: int
    crosscheck_count: Optional[int]
    pages: Tuple[str, ...]
    missing_from_official: Tuple[Tuple[str, str, str], ...] = ()
    missing_from_crosscheck: Tuple[Tuple[str, str, str], ...] = ()
    message: str = ""
    page_hashes: Tuple[Tuple[int, str], ...] = ()
    pages_contiguous: bool = False
    fetched_at: Optional[datetime] = None
    declared_count_evidence: Optional[str] = None
    crosscheck_coverage: str = "not_attempted"
    crosscheck_truncated: bool = False
    finalization: str = "not_finalized"
    t1_reconciliation: str = "not_executed_no_safe_machine_contract"
    unresolved_tickers: Tuple[str, ...] = ()
    crosscheck_requested_limit: Optional[int] = None
    crosscheck_reported_total: Optional[int] = None


@dataclass(frozen=True)
class _CrosscheckResult:
    records: Tuple[RawDisclosure, ...]
    requested_limit: int
    reported_total: Optional[int]
    coverage: str

    @property
    def possibly_truncated(self) -> bool:
        return len(self.records) >= self.requested_limit


class TDnetHTTPClient:
    """Small byte HTTP client with bounded retries and polite throttling."""

    def __init__(
        self,
        user_agent: str,
        *,
        public_page_permission_confirmed: bool = False,
        timeout: float = 15.0,
        max_retries: int = 2,
        requests_per_second: float = 0.5,
        opener: Callable[..., Any] = urlopen,
        clock: Callable[[], float] = time.monotonic,
        sleeper: Callable[[float], None] = time.sleep,
    ) -> None:
        if not public_page_permission_confirmed:
            raise ConnectorUnavailableError(
                "Explicit public-page permission capability is required."
            )
        if not user_agent.strip():
            raise ConnectorUnavailableError(
                TDNET_USER_AGENT_HELP
            )
        if timeout <= 0 or requests_per_second <= 0 or max_retries < 0:
            raise ValueError("Invalid TDnet HTTP client limits.")
        self._user_agent = user_agent.strip()
        self._timeout = timeout
        self._max_retries = max_retries
        self._minimum_interval = 1.0 / requests_per_second
        self._opener = opener
        self._clock = clock
        self._sleeper = sleeper
        self._last_request_at: Optional[float] = None
        self._lock = threading.Lock()

    def get_bytes(self, url: str, accept: str) -> bytes:
        for attempt in range(self._max_retries + 1):
            self._wait()
            request = Request(
                url,
                headers={"Accept": accept, "User-Agent": self._user_agent},
                method="GET",
            )
            try:
                with self._opener(request, timeout=self._timeout) as response:
                    return bytes(response.read())
            except HTTPError as error:
                if error.code not in RETRYABLE_STATUS_CODES or attempt == self._max_retries:
                    raise TDnetCollectionError(
                        f"TDnet request failed with HTTP {error.code}: {url}"
                    ) from error
            except (URLError, TimeoutError) as error:
                if attempt == self._max_retries:
                    raise TDnetCollectionError(
                        f"TDnet request failed after {attempt + 1} attempts: {url}"
                    ) from error
            self._sleeper(0.5 * (2**attempt))
        raise TDnetCollectionError(f"TDnet request failed: {url}")

    def _wait(self) -> None:
        with self._lock:
            now = self._clock()
            if self._last_request_at is not None:
                remaining = self._minimum_interval - (now - self._last_request_at)
                if remaining > 0:
                    self._sleeper(remaining)
                    now = self._clock()
            self._last_request_at = now


@dataclass
class _Cell:
    text: str
    links: List[str]


class _TDnetHTMLParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.page_links: Set[str] = set()
        self.rows: List[List[_Cell]] = []
        self.all_text: List[str] = []
        self._row: Optional[List[_Cell]] = None
        self._cell_text: Optional[List[str]] = None
        self._cell_links: Optional[List[str]] = None

    def handle_starttag(self, tag: str, attrs: Sequence[Tuple[str, Optional[str]]]) -> None:
        attributes = dict(attrs)
        href = attributes.get("href")
        if href:
            if self._cell_links is not None:
                self._cell_links.append(href)
        # TDnet pagination is exposed through attributes such as
        # onClick="pagerLink('I_list_002_YYYYMMDD.html')", not only href.
        # Extract only the matched local basename: never execute JavaScript or
        # preserve a host supplied inside an attribute value.
        for _, value in attrs:
            if value is None:
                continue
            for match in PAGE_LINK_PATTERN.finditer(value):
                self.page_links.add(match.group(0))
        if tag.lower() == "tr":
            self._row = []
        elif tag.lower() in {"td", "th"} and self._row is not None:
            self._cell_text = []
            self._cell_links = []

    def handle_data(self, data: str) -> None:
        self.all_text.append(data)
        if self._cell_text is not None:
            self._cell_text.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() in {"td", "th"} and self._row is not None and self._cell_text is not None:
            self._row.append(_Cell(
                text=_normalize_space("".join(self._cell_text)),
                links=list(self._cell_links or ()),
            ))
            self._cell_text = None
            self._cell_links = None
        elif tag.lower() == "tr" and self._row is not None:
            if self._row:
                self.rows.append(self._row)
            self._row = None


class TDnetConnector:
    """Source-wide, fail-closed collection of free TDnet public metadata."""

    name = "tdnet_public_web"
    source_wide_collection = True
    max_lookback_days = 30
    secret_fields = (
        SecretField(
            env="TDNET_USER_AGENT",
            label="TDnet User-Agent",
            kind="text",
            help=TDNET_USER_AGENT_HELP,
        ),
    )

    def __init__(
        self,
        client: TDnetHTTPClient,
        *,
        official_base_url: str = OFFICIAL_BASE_URL,
        yanoshin_base_url: str = YANOSHIN_BASE_URL,
        checkpoint_path: Optional[Path] = None,
        ledger_path: Optional[Path] = None,
        yanoshin_limit: int = DEFAULT_YANOSHIN_LIMIT,
        crosscheck_enabled: bool = True,
        now: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
    ) -> None:
        self._client = client
        self._official_base_url = official_base_url.rstrip("/") + "/"
        self._yanoshin_base_url = yanoshin_base_url.rstrip("/") + "/"
        self._checkpoint_path = checkpoint_path
        self._ledger_path = ledger_path
        if yanoshin_limit <= 0:
            raise ValueError("Yanoshin limit must be greater than zero.")
        self._yanoshin_limit = yanoshin_limit
        self._crosscheck_enabled = crosscheck_enabled
        self._now = now
        self._pending_checkpoint: Optional[date] = None
        self._last_reports: Tuple[TDnetRunReport, ...] = ()

    @classmethod
    def from_environment(cls) -> "TDnetConnector":
        user_agent = os.environ.get("TDNET_USER_AGENT", "").strip()
        permission_confirmed = _read_permission_confirmation()
        if not user_agent or not permission_confirmed:
            raise ConnectorUnavailableError(
                cls.configuration_error() or TDNET_USER_AGENT_HELP
            )
        checkpoint = os.environ.get(
            "TDNET_CHECKPOINT_PATH",
            "data/tdnet_checkpoint.json",
        ).strip()
        ledger = os.environ.get(
            "TDNET_LEDGER_PATH",
            "data/tdnet_completeness.jsonl",
        ).strip()
        return cls(
            TDnetHTTPClient(
                user_agent,
                public_page_permission_confirmed=True,
                timeout=_read_float("TDNET_TIMEOUT_SECONDS", 15.0),
                max_retries=_read_int("TDNET_MAX_RETRIES", 2),
                requests_per_second=_read_float("TDNET_REQUESTS_PER_SECOND", 0.5),
            ),
            checkpoint_path=Path(checkpoint) if checkpoint else None,
            ledger_path=Path(ledger) if ledger else None,
            yanoshin_limit=_read_int(
                "TDNET_YANOSHIN_LIMIT",
                DEFAULT_YANOSHIN_LIMIT,
            ),
            crosscheck_enabled=_read_bool("TDNET_YANOSHIN_CROSSCHECK_ENABLED", False),
        )

    @classmethod
    def configuration_error(cls) -> Optional[str]:
        if not os.environ.get("TDNET_USER_AGENT", "").strip():
            return TDNET_USER_AGENT_HELP
        if not _read_permission_confirmation():
            return (
                "TDNET_PUBLIC_PAGE_PERMISSION_CONFIRMED=true is required "
                "after the operator reviews robots guidance and obtains any "
                "permission required by JPX."
            )
        return None

    @property
    def last_reports(self) -> Tuple[TDnetRunReport, ...]:
        return self._last_reports

    def collect(self, request: CollectionRequest) -> List[InformationItem]:
        self._pending_checkpoint = None
        jp_tickers = tuple(
            ticker
            for ticker in request.tickers
            if request.market_for(ticker) == MARKET_JP
        )
        if not jp_tickers:
            self._last_reports = ()
            return []
        target_tickers_by_code: Dict[str, List[str]] = {}
        unresolved: List[str] = []
        for ticker in jp_tickers:
            normalized = _normalize_target_ticker(ticker)
            if normalized is None:
                unresolved.append(ticker)
            else:
                target_tickers_by_code.setdefault(normalized, []).append(ticker)
        if unresolved:
            report = TDnetRunReport(
                day=request.start_date,
                status=TDnetCompleteness.UNKNOWN,
                declared_count=None,
                official_count=0,
                crosscheck_count=None,
                pages=(),
                message="Unresolved Japanese ticker format; collection was not started.",
                unresolved_tickers=tuple(unresolved),
            )
            self._last_reports = (report,)
            self._persist_report(report)
            raise TDnetDataError(
                "Unresolved Japanese ticker format: " + ", ".join(unresolved)
            )

        effective_start = request.start_date
        checkpoint = self._read_checkpoint()
        if checkpoint is not None:
            oldest_available = (
                self._now().astimezone(JAPAN_TIME).date()
                - timedelta(days=self.max_lookback_days)
            )
            if checkpoint - timedelta(days=1) < oldest_available:
                report = TDnetRunReport(
                    day=request.start_date,
                    status=TDnetCompleteness.STALE,
                    declared_count=None,
                    official_count=0,
                    crosscheck_count=None,
                    pages=(),
                    message="historical_gap_requires_backfill",
                    finalization="blocked",
                )
                self._last_reports = (report,)
                self._persist_report(report)
                raise TDnetDataError("historical_gap_requires_backfill")
            effective_start = max(
                effective_start,
                checkpoint - timedelta(days=1),
            )
        reports: List[TDnetRunReport] = []
        all_disclosures: List[RawDisclosure] = []
        today_jp = self._now().astimezone(JAPAN_TIME).date()
        for day in _date_range(effective_start, request.end_date):
            official, report = self._collect_official_day(day)
            if not self._crosscheck_enabled:
                is_current_day = day >= today_jp
                completed_report = TDnetRunReport(
                    day=day,
                    status=(TDnetCompleteness.PROVISIONAL if is_current_day
                            else TDnetCompleteness.COMPLETE),
                    declared_count=report.declared_count,
                    official_count=len(official),
                    crosscheck_count=None,
                    pages=report.pages,
                    page_hashes=report.page_hashes,
                    pages_contiguous=report.pages_contiguous,
                    fetched_at=report.fetched_at,
                    declared_count_evidence=report.declared_count_evidence,
                    crosscheck_coverage="disabled_official_only",
                    finalization=("provisional_current_jp_day" if is_current_day
                                  else "historical_day_officially_finalized"),
                )
                reports.append(completed_report)
                self._persist_report(completed_report)
                all_disclosures.extend(official)
                continue
            try:
                crosscheck_result = self._collect_yanoshin_day(day)
            except TDnetCollectionError as error:
                report = TDnetRunReport(
                    day=day,
                    status=TDnetCompleteness.UNKNOWN,
                    declared_count=report.declared_count,
                    official_count=report.official_count,
                    crosscheck_count=None,
                    pages=report.pages,
                    message=f"Yanoshin cross-check unavailable: {error}",
                    page_hashes=report.page_hashes,
                    pages_contiguous=report.pages_contiguous,
                    fetched_at=report.fetched_at,
                    declared_count_evidence=report.declared_count_evidence,
                    crosscheck_coverage=(
                        getattr(error, "crosscheck_coverage", None)
                        or "unavailable"
                    ),
                    crosscheck_requested_limit=self._yanoshin_limit,
                    crosscheck_reported_total=getattr(
                        error,
                        "crosscheck_reported_total",
                        None,
                    ),
                    finalization="blocked",
                )
                reports.append(report)
                self._persist_report(report)
                self._last_reports = tuple(reports)
                raise TDnetCollectionError(report.message) from error

            crosscheck = crosscheck_result.records
            if crosscheck_result.possibly_truncated:
                report = TDnetRunReport(
                    day=day,
                    status=TDnetCompleteness.UNKNOWN,
                    declared_count=report.declared_count,
                    official_count=report.official_count,
                    crosscheck_count=len(crosscheck),
                    pages=report.pages,
                    message=(
                        "Yanoshin reached the requested response limit; "
                        "coverage cannot be established without confirmed pagination."
                    ),
                    page_hashes=report.page_hashes,
                    pages_contiguous=report.pages_contiguous,
                    fetched_at=report.fetched_at,
                    declared_count_evidence=report.declared_count_evidence,
                    crosscheck_coverage="requested_limit_reached",
                    crosscheck_truncated=True,
                    crosscheck_requested_limit=crosscheck_result.requested_limit,
                    crosscheck_reported_total=crosscheck_result.reported_total,
                    finalization="blocked",
                )
                reports.append(report)
                self._persist_report(report)
                self._last_reports = tuple(reports)
                raise TDnetCollectionError(report.message)

            official_counts = Counter(
                item.comparison_key for item in official
            )
            crosscheck_counts = Counter(
                item.comparison_key for item in crosscheck
            )
            missing = tuple(
                sorted((crosscheck_counts - official_counts).elements())
            )
            missing_from_crosscheck = tuple(
                sorted((official_counts - crosscheck_counts).elements())
            )
            if missing or missing_from_crosscheck:
                report = TDnetRunReport(
                    day=day,
                    status=TDnetCompleteness.RECONCILIATION_REQUIRED,
                    declared_count=report.declared_count,
                    official_count=len(official),
                    crosscheck_count=len(crosscheck),
                    pages=report.pages,
                    missing_from_official=missing,
                    missing_from_crosscheck=missing_from_crosscheck,
                    message=(
                        "Official and unofficial cross-check multiplicities "
                        "do not match in both directions."
                    ),
                    page_hashes=report.page_hashes,
                    pages_contiguous=report.pages_contiguous,
                    fetched_at=report.fetched_at,
                    declared_count_evidence=report.declared_count_evidence,
                    crosscheck_coverage=crosscheck_result.coverage,
                    crosscheck_requested_limit=crosscheck_result.requested_limit,
                    crosscheck_reported_total=crosscheck_result.reported_total,
                    finalization="blocked",
                )
                reports.append(report)
                self._persist_report(report)
                self._last_reports = tuple(reports)
                raise TDnetCollectionError(
                    "TDnet reconciliation required for "
                    f"{day.isoformat()}: official_missing={len(missing)} "
                    f"crosscheck_missing={len(missing_from_crosscheck)}"
                )
            is_current_day = day >= today_jp
            completed_report = TDnetRunReport(
                day=day,
                status=(
                    TDnetCompleteness.PROVISIONAL
                    if is_current_day
                    else TDnetCompleteness.COMPLETE
                ),
                declared_count=report.declared_count,
                official_count=len(official),
                crosscheck_count=len(crosscheck),
                pages=report.pages,
                page_hashes=report.page_hashes,
                pages_contiguous=report.pages_contiguous,
                fetched_at=report.fetched_at,
                declared_count_evidence=report.declared_count_evidence,
                crosscheck_coverage=crosscheck_result.coverage,
                missing_from_crosscheck=missing_from_crosscheck,
                crosscheck_requested_limit=crosscheck_result.requested_limit,
                crosscheck_reported_total=crosscheck_result.reported_total,
                finalization=("provisional_current_jp_day" if is_current_day else "historical_day_finalized"),
            )
            reports.append(completed_report)
            self._persist_report(completed_report)
            all_disclosures.extend(official)

        self._last_reports = tuple(reports)
        complete_days = [
            report.day
            for report in reports
            if report.status is TDnetCompleteness.COMPLETE
        ]
        self._pending_checkpoint = max(complete_days) if complete_days else None
        collected_at = self._now().astimezone(timezone.utc)
        items = [
            self._to_information_item(
                disclosure,
                collected_at,
                tuple(
                    target_tickers_by_code[
                        _normalize_company_code(disclosure.company_code)
                    ]
                ),
            )
            for disclosure in all_disclosures
            if _normalize_company_code(disclosure.company_code)
            in target_tickers_by_code
        ]
        return sorted(items, key=lambda item: (item.published_at, item.external_id))

    def commit_checkpoint(self) -> None:
        """Persist only a checkpoint produced by a complete, reconciled run."""
        if self._pending_checkpoint is None or self._checkpoint_path is None:
            return
        if not self._last_reports or any(
            report.status
            not in {TDnetCompleteness.COMPLETE, TDnetCompleteness.PROVISIONAL}
            for report in self._last_reports
        ):
            raise TDnetCollectionError("Refusing to advance an incomplete TDnet checkpoint.")
        payload = {
            "source": self.name,
            "last_complete_date": self._pending_checkpoint.isoformat(),
            "committed_at": self._now().astimezone(timezone.utc).isoformat(),
            "status": TDnetCompleteness.COMPLETE.value,
        }
        self._checkpoint_path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self._checkpoint_path.with_suffix(self._checkpoint_path.suffix + ".tmp")
        temporary.write_text(json.dumps(payload, sort_keys=True) + "\n", encoding="utf-8")
        temporary.replace(self._checkpoint_path)
        self._pending_checkpoint = None

    def _read_checkpoint(self) -> Optional[date]:
        if self._checkpoint_path is None or not self._checkpoint_path.exists():
            return None
        try:
            payload = json.loads(self._checkpoint_path.read_text(encoding="utf-8"))
            if not isinstance(payload, dict):
                raise ValueError("checkpoint must be an object")
            if payload.get("source") != self.name or payload.get("status") != "complete":
                raise ValueError("checkpoint source or status is invalid")
            value = date.fromisoformat(str(payload["last_complete_date"]))
        except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError) as error:
            raise TDnetDataError(
                "TDnet checkpoint is corrupt; refusing collection until it is repaired."
            ) from error
        if value >= self._now().astimezone(JAPAN_TIME).date():
            raise TDnetDataError(
                "TDnet checkpoint is not a finalized historical Japanese date."
            )
        return value

    def _persist_report(self, report: TDnetRunReport) -> None:
        if self._ledger_path is None:
            return
        payload = {
            "source": self.name,
            "day": report.day.isoformat(),
            "status": report.status.value,
            "declared_count": report.declared_count,
            "official_count": report.official_count,
            "crosscheck_count": report.crosscheck_count,
            "pages": list(report.pages),
            "missing_from_official": [list(key) for key in report.missing_from_official],
            "missing_from_crosscheck": [
                list(key) for key in report.missing_from_crosscheck
            ],
            "message": report.message,
            "fetched_at": (
                report.fetched_at.astimezone(timezone.utc).isoformat()
                if report.fetched_at
                else self._now().astimezone(timezone.utc).isoformat()
            ),
            "page_hashes": [
                {"page": page_number, "sha256": page_hash}
                for page_number, page_hash in report.page_hashes
            ],
            "pages_contiguous": report.pages_contiguous,
            "declared_count_evidence": report.declared_count_evidence,
            "crosscheck_coverage": report.crosscheck_coverage,
            "crosscheck_truncated": report.crosscheck_truncated,
            "finalization": report.finalization,
            "t1_reconciliation": report.t1_reconciliation,
            "unresolved_tickers": list(report.unresolved_tickers),
            "crosscheck_requested_limit": report.crosscheck_requested_limit,
            "crosscheck_reported_total": report.crosscheck_reported_total,
        }
        self._ledger_path.parent.mkdir(parents=True, exist_ok=True)
        with self._ledger_path.open("a", encoding="utf-8") as ledger:
            ledger.write(json.dumps(payload, sort_keys=True) + "\n")

    def _collect_official_day(self, day: date) -> Tuple[List[RawDisclosure], TDnetRunReport]:
        day_text = day.strftime("%Y%m%d")
        pending = [urljoin(self._official_base_url, OFFICIAL_PAGE.format(page=1, day=day_text))]
        visited: Set[str] = set()
        disclosures: List[RawDisclosure] = []
        declared_counts: Set[int] = set()
        declared_evidence: Set[str] = set()
        page_hashes: Dict[int, str] = {}
        fetched_at = self._now().astimezone(timezone.utc)
        while pending:
            page_url = pending.pop(0)
            if page_url in visited:
                continue
            body = self._client.get_bytes(page_url, "text/html,application/xhtml+xml")
            parser = _parse_html(body, page_url)
            visited.add(page_url)
            match = _declared_count_match(parser.all_text)
            count = match[0] if match else None
            if count is None and OFFICIAL_EMPTY_TEXT in _normalize_space("".join(parser.all_text)):
                count = 0
                match = (0, OFFICIAL_EMPTY_TEXT)
            if count is not None:
                declared_counts.add(count)
                declared_evidence.add(match[1])
            page_match = PAGE_LINK_PATTERN.search(page_url)
            if page_match is None:
                raise TDnetDataError(f"Cannot determine TDnet page number: {page_url}")
            page_number = int(page_match.group(1))
            page_hashes[page_number] = sha256(body).hexdigest()
            disclosures.extend(_parse_official_rows(parser.rows, day, page_url))
            for href in sorted(parser.page_links):
                match = PAGE_LINK_PATTERN.search(href)
                if match and match.group(2) == day_text:
                    candidate = urljoin(page_url, href)
                    if candidate not in visited and candidate not in pending:
                        pending.append(candidate)

        page_numbers = sorted(page_hashes)
        pages_contiguous = page_numbers == list(range(1, len(page_numbers) + 1))
        report_details = {
            "page_hashes": tuple(sorted(page_hashes.items())),
            "pages_contiguous": pages_contiguous,
            "fetched_at": fetched_at,
            "declared_count_evidence": " | ".join(sorted(declared_evidence)) or None,
        }
        if not pages_contiguous:
            report = TDnetRunReport(
                day,
                TDnetCompleteness.PARTIAL,
                next(iter(declared_counts)) if len(declared_counts) == 1 else None,
                len(disclosures),
                None,
                tuple(sorted(visited)),
                message="Official TDnet page numbers are not contiguous from page 1.",
                finalization="blocked",
                **report_details,
            )
            self._last_reports = (report,)
            self._persist_report(report)
            raise TDnetDataError(report.message)
        if not declared_counts or len(declared_counts) != 1:
            status = TDnetCompleteness.UNKNOWN
            report = TDnetRunReport(
                day, status, None, len(disclosures), None,
                tuple(sorted(visited)),
                message="Official declared count is absent or inconsistent.",
                finalization="blocked",
                **report_details,
            )
            self._last_reports = (report,)
            self._persist_report(report)
            raise TDnetDataError(f"TDnet completeness is unknown for {day.isoformat()}: {report.message}")
        declared = next(iter(declared_counts))
        deduplicated = {item.comparison_key + (item.document_url,): item for item in disclosures}
        disclosures = list(deduplicated.values())
        if len(disclosures) != declared:
            report = TDnetRunReport(
                day, TDnetCompleteness.PARTIAL, declared, len(disclosures), None,
                tuple(sorted(visited)),
                message="Parsed record count does not match the official declared count.",
                finalization="blocked",
                **report_details,
            )
            self._last_reports = (report,)
            self._persist_report(report)
            raise TDnetDataError(
                f"TDnet partial collection for {day.isoformat()}: declared={declared} parsed={len(disclosures)}"
            )
        return disclosures, TDnetRunReport(
            day, TDnetCompleteness.COMPLETE, declared, len(disclosures), None,
            tuple(sorted(visited)),
            finalization="pending_crosscheck",
            **report_details,
        )

    def _collect_yanoshin_day(self, day: date) -> _CrosscheckResult:
        base_url = urljoin(
            self._yanoshin_base_url,
            f"{day.strftime('%Y%m%d')}.json",
        )
        url = f"{base_url}?{urlencode({'limit': self._yanoshin_limit})}"
        body = self._client.get_bytes(url, "application/json")
        try:
            payload = json.loads(body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise TDnetDataError("Yanoshin returned invalid JSON.") from error
        reported_total: Optional[int]
        coverage: str
        if isinstance(payload, dict):
            items = payload.get("items")
            total_count = payload.get("total_count")
            if not isinstance(items, list):
                raise TDnetDataError(
                    "Yanoshin wrapper items must be a JSON list.",
                    crosscheck_reported_total=(
                        total_count if isinstance(total_count, int) else None
                    ),
                    crosscheck_coverage="invalid_wrapper_items",
                )
            if (
                not isinstance(total_count, int)
                or isinstance(total_count, bool)
                or total_count < 0
            ):
                raise TDnetDataError(
                    "Yanoshin wrapper total_count must be a non-negative integer.",
                    crosscheck_coverage="invalid_reported_total",
                )
            if total_count != len(items):
                raise TDnetDataError(
                    "Yanoshin total_count does not match the returned items length.",
                    crosscheck_reported_total=total_count,
                    crosscheck_coverage="reported_total_mismatch",
                )
            record_payload = items
            reported_total = total_count
            coverage = "wrapper_count_matches_below_requested_limit"
        elif isinstance(payload, list):
            record_payload = payload
            reported_total = None
            coverage = "legacy_list_fixture_no_reported_total"
        else:
            raise TDnetDataError(
                "Yanoshin payload must be a wrapper object or legacy JSON list."
            )
        records = tuple(_parse_yanoshin(record_payload, day, url))
        return _CrosscheckResult(
            records=records,
            requested_limit=self._yanoshin_limit,
            reported_total=reported_total,
            coverage=coverage,
        )

    def _to_information_item(
        self,
        raw: RawDisclosure,
        collected_at: datetime,
        tickers: Tuple[str, ...],
    ) -> InformationItem:
        published_utc = raw.published_local.astimezone(timezone.utc)
        canonical_document_url = _canonicalize_url(raw.document_url)
        snapshot_material = json.dumps(
            {
                "raw_cells": list(raw.raw_cells),
                "document_url": canonical_document_url,
                "xbrl_url": raw.xbrl_url,
                "published_local": raw.published_local.isoformat(),
                "company_code": raw.company_code,
            },
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        raw_content_hash = sha256(snapshot_material.encode("utf-8")).hexdigest()
        identity_material = canonical_document_url
        external_id = "synthetic:" + sha256(identity_material.encode("utf-8")).hexdigest()
        raw_payload = {
            "provider": "jpx_tdnet_public_web",
            "official_source_url": raw.page_url,
            "document_url": raw.document_url,
            "canonical_document_url": canonical_document_url,
            "xbrl_url": raw.xbrl_url,
            "company_code": raw.company_code,
            "company_name": raw.company_name,
            "published_local": raw.published_local.isoformat(),
            "published_timezone": "Asia/Tokyo",
            "timezone_basis": "operational_assumption_pending_official_confirmation",
            "raw_cells": list(raw.raw_cells),
            "raw_content_hash": raw_content_hash,
            "identity_basis": "canonical_document_url",
            "official_id_available": False,
            "revision_semantics": "pending_unresolved_no_confirmed_public_field",
            "withdrawal_semantics": "pending_unresolved_no_confirmed_public_field",
        }
        return InformationItem(
            source=self.name,
            source_type="regulatory_disclosure",
            external_id=external_id,
            tickers=tickers,
            issuer=raw.company_name,
            published_at=published_utc,
            title=raw.title,
            document_type="tdnet_timely_disclosure",
            url=raw.document_url,
            collected_at=collected_at,
            raw_metadata=raw_payload,
            market=MARKET_JP,
            effective_at=published_utc,
        )


def _parse_html(body: bytes, page_url: str) -> _TDnetHTMLParser:
    text: Optional[str] = None
    for encoding in ("utf-8", "cp932", "shift_jis"):
        try:
            text = body.decode(encoding)
            break
        except UnicodeDecodeError:
            continue
    if text is None:
        raise TDnetDataError(f"TDnet page encoding is unsupported: {page_url}")
    parser = _TDnetHTMLParser()
    parser.feed(text)
    return parser


def _declared_count(text_parts: Iterable[str]) -> Optional[int]:
    match = _declared_count_match(text_parts)
    return match[0] if match else None


def _declared_count_match(
    text_parts: Iterable[str],
) -> Optional[Tuple[int, str]]:
    text = _normalize_space(" ".join(text_parts))
    for pattern in DECLARED_COUNT_PATTERNS:
        match = pattern.search(text)
        if match:
            return int(match.group(1).replace(",", "")), match.group(0)
    return None


def _parse_official_rows(rows: Iterable[List[_Cell]], day: date, page_url: str) -> List[RawDisclosure]:
    output: List[RawDisclosure] = []
    for cells in rows:
        texts = [cell.text for cell in cells]
        time_match = next((TIME_PATTERN.search(text) for text in texts if TIME_PATTERN.search(text)), None)
        code_match = next((COMPANY_CODE_PATTERN.search(text) for text in texts if COMPANY_CODE_PATTERN.search(text)), None)
        links = [(cell.text, href) for cell in cells for href in cell.links]
        document = next(
            (
                (text, urljoin(page_url, href))
                for text, href in links
                if href.lower().split("?", 1)[0].endswith(".pdf")
                and "xbrl" not in href.lower()
            ),
            None,
        )
        if time_match is None or code_match is None or document is None:
            continue
        hour, minute = int(time_match.group(1)), int(time_match.group(2))
        if hour > 23:
            continue
        code = code_match.group(1).upper()
        title = _normalize_space(document[0])
        if not title:
            continue
        code_index = next(i for i, text in enumerate(texts) if COMPANY_CODE_PATTERN.search(text))
        company_name = texts[code_index + 1] if code_index + 1 < len(texts) else ""
        if not company_name or company_name == title:
            company_name = code
        xbrl = next((urljoin(page_url, href) for _, href in links if "xbrl" in href.lower()), None)
        output.append(RawDisclosure(
            company_code=code,
            company_name=company_name,
            published_local=datetime.combine(day, datetime_time(hour, minute), tzinfo=JAPAN_TIME),
            title=title,
            document_url=document[1],
            xbrl_url=xbrl,
            page_url=page_url,
            raw_cells=tuple(texts),
        ))
    return output


def _parse_yanoshin(payload: Any, day: date, source_url: str) -> List[RawDisclosure]:
    if not isinstance(payload, list):
        raise TDnetDataError("Yanoshin payload must be a JSON list.")
    output: List[RawDisclosure] = []
    for wrapper in payload:
        record = wrapper.get("Tdnet") if isinstance(wrapper, dict) and isinstance(wrapper.get("Tdnet"), dict) else wrapper
        if not isinstance(record, dict):
            raise TDnetDataError("Yanoshin record has an unexpected shape.")
        try:
            code = str(record["company_code"]).strip()
            title = str(record["title"]).strip()
            name = str(record.get("company_name") or code).strip()
            pubdate = str(record["pubdate"]).strip()
        except KeyError as error:
            raise TDnetDataError("Yanoshin record is missing a comparison field.") from error
        published = _parse_yanoshin_datetime(pubdate, day)
        document_url = str(record.get("document_url") or record.get("url") or source_url)
        output.append(RawDisclosure(code, name, published, title, document_url, None, source_url, tuple(str(record.get(key, "")) for key in sorted(record))))
    return output


def _parse_yanoshin_datetime(value: str, fallback_day: date) -> datetime:
    for pattern in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y/%m/%d %H:%M:%S", "%H:%M"):
        try:
            parsed = datetime.strptime(value, pattern)
            if pattern == "%H:%M":
                parsed = datetime.combine(fallback_day, parsed.time())
            return parsed.replace(tzinfo=JAPAN_TIME)
        except ValueError:
            continue
    raise TDnetDataError(f"Yanoshin pubdate is unsupported: {value!r}")


def _normalize_company_code(value: str) -> str:
    return re.sub(r"[^0-9A-Z]", "", value.strip().upper())


def _normalize_target_ticker(value: str) -> Optional[str]:
    match = TARGET_TICKER_PATTERN.fullmatch(value.strip().upper())
    return match.group("code") if match else None


def _canonicalize_url(value: str) -> str:
    parsed = urlsplit(value.strip())
    if parsed.scheme.lower() not in {"http", "https"} or not parsed.netloc:
        raise TDnetDataError(f"TDnet document URL is not canonicalizable: {value!r}")
    path = re.sub(r"/{2,}", "/", parsed.path)
    query = urlencode(sorted(parse_qsl(parsed.query, keep_blank_values=True)))
    return urlunsplit(
        (parsed.scheme.lower(), parsed.netloc.lower(), path, query, "")
    )


def _normalize_text(value: str) -> str:
    return _normalize_space(value).casefold()


def _normalize_space(value: str) -> str:
    return " ".join(value.replace("\u3000", " ").split())


def _date_range(start: date, end: date) -> Iterable[date]:
    current = start
    while current <= end:
        yield current
        current += timedelta(days=1)


def _read_float(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, str(default)))
    except ValueError as error:
        raise ConnectorUnavailableError(f"{name} must be numeric.") from error


def _read_int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, str(default)))
    except ValueError as error:
        raise ConnectorUnavailableError(f"{name} must be an integer.") from error


def _read_permission_confirmation() -> bool:
    return (
        os.environ.get("TDNET_PUBLIC_PAGE_PERMISSION_CONFIRMED", "")
        .strip()
        .lower()
        == "true"
    )


def _read_bool(name: str, default: bool) -> bool:
    value = os.environ.get(name)
    if value is None or not value.strip():
        return default
    normalized = value.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise ValueError(f"{name} must be true or false")
