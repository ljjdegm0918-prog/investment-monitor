"""Source-independent information collection."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
import logging
import os
from typing import Iterable, List, Mapping, Optional, Protocol, Sequence, Tuple

from .connectors.base import SourceConnector
from .models import CollectionRequest, InformationItem, MARKET_UNKNOWN
from .repository import InformationRepository, SaveResult

LOGGER = logging.getLogger(__name__)


class CollectedItemFilter(Protocol):
    """Optional pre-persistence filter for standardized collected items."""

    def filter(
        self,
        items: Sequence[InformationItem],
    ) -> List[InformationItem]:
        """Return the items that are allowed to be persisted."""


@dataclass(frozen=True)
class CollectionFailure:
    """One source/ticker pair that failed while other work continued."""

    source: str
    ticker: str
    message: str
    feed: Optional[str] = None
    url: Optional[str] = None


@dataclass(frozen=True)
class CollectionEvent:
    """One truthful source/ticker collection operation for durable activity logs."""

    source: str
    ticker: str
    started_at: datetime
    finished_at: datetime
    status: str
    records_read: int
    records_written: int
    records_inserted: int
    records_updated: int
    duplicate_records: int
    error_message: Optional[str] = None
    market: str = "unknown"
    requested_start_date: Optional[date] = None
    requested_end_date: Optional[date] = None
    effective_start_date: Optional[date] = None
    effective_end_date: Optional[date] = None
    coverage_kind: str = "unknown"
    initial_backfill: bool = False


def _circuit_breaker_threshold() -> int:
    """Read the per-source circuit breaker threshold (default 2)."""
    raw = os.environ.get("COLLECTION_CIRCUIT_BREAKER_THRESHOLD")
    if raw is None:
        return 2
    try:
        return max(1, int(raw))
    except ValueError:
        return 2


class _SourceCircuitBreaker:
    """Per-source consecutive-failure circuit breaker for one collect() round.

    同一 source 连续失败达到阈值后熔断，本轮跳过该 source 剩余 ticker；
    一次成功（或非失败）尝试即重置连续失败计数。
    """

    def __init__(self, threshold: int) -> None:
        self._threshold = max(1, int(threshold))
        self._consecutive_failures: dict[str, int] = {}
        self._open: set[str] = set()

    def is_open(self, source: str) -> bool:
        return source in self._open

    def record_failure(self, source: str) -> None:
        count = self._consecutive_failures.get(source, 0) + 1
        self._consecutive_failures[source] = count
        if count >= self._threshold:
            self._open.add(source)

    def record_success(self, source: str) -> None:
        self._consecutive_failures[source] = 0

    def message(self, source: str) -> str:
        return (
            f"circuit_open: {source} skipped remaining tickers after "
            f"{self._threshold} consecutive failures"
        )


class CollectionPipeline:
    """Collect and persist each source/ticker pair independently."""

    def __init__(
        self,
        connectors: Iterable[SourceConnector],
        repository: Optional[InformationRepository] = None,
        logger: logging.Logger = LOGGER,
        initial_backfill: bool = False,
        source_markets: Optional[Mapping[str, str]] = None,
        item_filter: Optional[CollectedItemFilter] = None,
    ) -> None:
        self._connectors = tuple(connectors)
        self._repository = repository
        self._logger = logger
        self._initial_backfill = initial_backfill
        self._source_markets = dict(source_markets or {})
        self._item_filter = item_filter
        self._last_failures: Tuple[CollectionFailure, ...] = ()
        self._last_save_result = SaveResult()
        self._last_events: Tuple[CollectionEvent, ...] = ()

    @property
    def last_failures(self) -> Tuple[CollectionFailure, ...]:
        return self._last_failures

    @property
    def last_save_result(self) -> SaveResult:
        return self._last_save_result

    @property
    def last_events(self) -> Tuple[CollectionEvent, ...]:
        return self._last_events

    def collect(self, request: CollectionRequest) -> List[InformationItem]:
        """Collect each ticker from each source and save successful results."""
        items: List[InformationItem] = []
        failures: List[CollectionFailure] = []
        events: List[CollectionEvent] = []
        save_result = SaveResult()
        breaker = _SourceCircuitBreaker(_circuit_breaker_threshold())

        for connector in self._connectors:
            if bool(getattr(connector, "source_wide_collection", False)):
                started_at = datetime.now(timezone.utc)
                source_start_date = request.start_date
                try:
                    source_start_date = self._clamped_start_date(
                        connector,
                        request.start_date,
                        request.end_date,
                    )
                    source_request = CollectionRequest(
                        tickers=request.tickers,
                        start_date=source_start_date,
                        end_date=request.end_date,
                        markets=request.markets,
                    )
                    raw_collected = connector.collect(source_request)
                    collected = self._filter_collected(raw_collected)
                    source_save = SaveResult()
                    if collected and self._repository is not None:
                        source_save = self._repository.save(collected)
                    commit_checkpoint = getattr(
                        connector,
                        "commit_checkpoint",
                        None,
                    )
                    if self._repository is not None and callable(commit_checkpoint):
                        commit_checkpoint()
                    save_result = save_result + source_save
                    items.extend(collected)
                    status_hint = str(
                        getattr(connector, "last_collection_status", "") or ""
                    )
                    failure_details = self._connector_failure_details(connector)
                    error_message = None
                    if status_hint in {"partial", "failure"}:
                        status = status_hint
                        error_message = "; ".join(
                            self._format_failure_detail(detail)
                            for detail in failure_details
                        ) or f"connector reported {status_hint} collection"
                        if failure_details:
                            failures.extend(
                                CollectionFailure(
                                    source=connector.name,
                                    ticker="*",
                                    message=self._format_failure_detail(detail),
                                    feed=detail.get("feed"),
                                    url=detail.get("url"),
                                )
                                for detail in failure_details
                            )
                        else:
                            failures.append(CollectionFailure(
                                source=connector.name,
                                ticker="*",
                                message=error_message,
                            ))
                        self._logger.warning(
                            "collection source=%s ticker=* status=%s error=%s",
                            connector.name,
                            status,
                            error_message,
                        )
                    elif status_hint in {"success", "empty"}:
                        status = status_hint
                    else:
                        # Preserve legacy source-wide behavior (notably TDnet)
                        # when a connector exposes no structured outcome.
                        status = "success" if collected else "empty"
                    events.append(CollectionEvent(
                        source=connector.name,
                        ticker="*",
                        started_at=started_at,
                        finished_at=datetime.now(timezone.utc),
                        status=status,
                        records_read=int(
                            getattr(connector, "last_records_read", len(raw_collected))
                        ),
                        records_written=source_save.inserted + source_save.updated,
                        records_inserted=source_save.inserted,
                        records_updated=source_save.updated,
                        duplicate_records=source_save.updated,
                        error_message=error_message,
                        requested_start_date=request.start_date,
                        requested_end_date=request.end_date,
                        effective_start_date=source_start_date,
                        effective_end_date=request.end_date,
                        coverage_kind=self._coverage_kind(
                            connector,
                            request.start_date,
                            source_start_date,
                        ),
                        initial_backfill=self._initial_backfill,
                    ))
                except Exception as error:
                    message = str(error) or error.__class__.__name__
                    failures.append(CollectionFailure(
                        source=connector.name,
                        ticker="*",
                        message=message,
                    ))
                    self._logger.error(
                        "collection source=%s ticker=* status=failure error=%s",
                        connector.name,
                        message,
                    )
                    events.append(CollectionEvent(
                        source=connector.name,
                        ticker="*",
                        started_at=started_at,
                        finished_at=datetime.now(timezone.utc),
                        status="failure",
                        records_read=0,
                        records_written=0,
                        records_inserted=0,
                        records_updated=0,
                        duplicate_records=0,
                        error_message=message,
                        requested_start_date=request.start_date,
                        requested_end_date=request.end_date,
                        effective_start_date=source_start_date,
                        effective_end_date=request.end_date,
                        coverage_kind=self._coverage_kind(
                            connector,
                            request.start_date,
                            source_start_date,
                        ),
                        initial_backfill=self._initial_backfill,
                    ))
                continue
            declared_market = self._source_markets.get(connector.name)
            if declared_market is None:
                connector_tickers = request.tickers
            else:
                # 多市场源（如 Nasdaq Baltic 覆盖 ee/lv/lt）用 frozenset 声明
                # 范围；这里展开成集合后比较，避免把整个 frozenset 当单值。
                declared_markets = (
                    set(declared_market)
                    if isinstance(
                        declared_market,
                        (tuple, list, set, frozenset),
                    )
                    else {declared_market}
                )
                connector_tickers = tuple(
                    ticker
                    for ticker in request.tickers
                    if request.market_for(ticker)
                    in declared_markets | {MARKET_UNKNOWN}
                )
            for ticker in connector_tickers:
                if breaker.is_open(connector.name):
                    message = breaker.message(connector.name)
                    skipped_at = datetime.now(timezone.utc)
                    failures.append(CollectionFailure(
                        source=connector.name,
                        ticker=ticker,
                        message=message,
                    ))
                    events.append(CollectionEvent(
                        source=connector.name,
                        ticker=ticker,
                        started_at=skipped_at,
                        finished_at=skipped_at,
                        status="failure",
                        records_read=0,
                        records_written=0,
                        records_inserted=0,
                        records_updated=0,
                        duplicate_records=0,
                        error_message=message,
                        market=request.market_for(ticker),
                        requested_start_date=request.start_date,
                        requested_end_date=request.end_date,
                        effective_start_date=request.start_date,
                        effective_end_date=request.end_date,
                        coverage_kind="unknown",
                        initial_backfill=self._initial_backfill,
                    ))
                    self._logger.warning(
                        "collection source=%s ticker=%s circuit_open",
                        connector.name,
                        ticker,
                    )
                    continue
                started_at = datetime.now(timezone.utc)
                ticker_start_date = self._clamped_start_date(
                    connector,
                    request.start_date,
                    request.end_date,
                )
                ticker_request = CollectionRequest(
                    tickers=(ticker,),
                    start_date=ticker_start_date,
                    end_date=request.end_date,
                    markets={ticker: request.market_for(ticker)},
                )
                try:
                    raw_collected = connector.collect(ticker_request)
                    collected = self._filter_collected(raw_collected)
                    per_ticker_save = SaveResult()
                    if collected and self._repository is not None:
                        per_ticker_save = self._repository.save(collected)
                    save_result = save_result + per_ticker_save
                    items.extend(collected)
                    status_hint = str(
                        getattr(connector, "last_collection_status", "") or ""
                    )
                    failure_details = self._connector_failure_details(connector)
                    connector_error = (
                        None
                        if collected
                        else self._connector_error_for_ticker(connector, ticker)
                    )
                    if status_hint == "partial":
                        event_status = "partial"
                        for detail in failure_details:
                            failures.append(CollectionFailure(
                                source=connector.name,
                                ticker=ticker,
                                message=self._format_failure_detail(detail),
                                feed=detail.get("feed"),
                                url=detail.get("url"),
                            ))
                        connector_error = "; ".join(
                            self._format_failure_detail(detail)
                            for detail in failure_details
                        ) or connector_error or "connector reported partial failure"
                        self._logger.warning(
                            "collection source=%s ticker=%s status=partial error=%s",
                            connector.name,
                            ticker,
                            connector_error,
                        )
                    elif status_hint == "failure" and failure_details:
                        event_status = "failure"
                        connector_error = "; ".join(
                            self._format_failure_detail(detail)
                            for detail in failure_details
                        )
                        failures.append(CollectionFailure(
                            source=connector.name,
                            ticker=ticker,
                            message=connector_error,
                            feed=",".join(
                                str(detail["feed"])
                                for detail in failure_details
                                if detail.get("feed")
                            ) or None,
                            url=",".join(
                                str(detail["url"])
                                for detail in failure_details
                                if detail.get("url")
                            ) or None,
                        ))
                        self._logger.error(
                            "collection source=%s ticker=%s status=failure error=%s",
                            connector.name,
                            ticker,
                            connector_error,
                        )
                    elif (
                        status_hint == "stub"
                        and not bool(getattr(connector, "live_path_attempted", False))
                    ):
                        event_status = "empty"
                        self._logger.info(
                            "collection source=%s ticker=%s status=stub treated_as=empty",
                            connector.name,
                            ticker,
                        )
                    elif connector_error:
                        event_status = "failure"
                        failures.append(CollectionFailure(
                            source=connector.name,
                            ticker=ticker,
                            message=connector_error,
                        ))
                        self._logger.error(
                            "collection source=%s ticker=%s status=failure error=%s",
                            connector.name,
                            ticker,
                            connector_error,
                        )
                    elif collected or status_hint == "success":
                        event_status = "success"
                        self._logger.info(
                            "collection source=%s ticker=%s status=success "
                            "items=%d inserted=%d updated=%d",
                            connector.name,
                            ticker,
                            len(collected),
                            per_ticker_save.inserted,
                            per_ticker_save.updated,
                        )
                    else:
                        event_status = "empty"
                        self._logger.info(
                            "collection source=%s ticker=%s status=empty items=0",
                            connector.name,
                            ticker,
                        )
                    events.append(CollectionEvent(
                        source=connector.name,
                        ticker=ticker,
                        started_at=started_at,
                        finished_at=datetime.now(timezone.utc),
                        status=event_status,
                        records_read=int(
                            getattr(connector, "last_records_read", len(raw_collected))
                        ),
                        records_written=per_ticker_save.inserted + per_ticker_save.updated,
                        records_inserted=per_ticker_save.inserted,
                        records_updated=per_ticker_save.updated,
                        duplicate_records=per_ticker_save.updated,
                        error_message=connector_error,
                        market=request.market_for(ticker),
                        requested_start_date=request.start_date,
                        requested_end_date=request.end_date,
                        effective_start_date=ticker_start_date,
                        effective_end_date=request.end_date,
                        coverage_kind=self._coverage_kind(
                            connector,
                            request.start_date,
                            ticker_start_date,
                        ),
                        initial_backfill=self._initial_backfill,
                    ))
                    if event_status == "failure":
                        breaker.record_failure(connector.name)
                    else:
                        breaker.record_success(connector.name)
                except Exception as error:
                    message = str(error) or error.__class__.__name__
                    failure_details = self._connector_failure_details(connector)
                    if failure_details:
                        failures.extend(
                            CollectionFailure(
                                source=connector.name,
                                ticker=ticker,
                                message=detail["message"],
                                feed=detail.get("feed"),
                                url=detail.get("url"),
                            )
                            for detail in failure_details
                        )
                        message = "; ".join(
                            self._format_failure_detail(detail)
                            for detail in failure_details
                        )
                    else:
                        failures.append(CollectionFailure(
                            source=connector.name,
                            ticker=ticker,
                            message=message,
                        ))
                    self._logger.error(
                        "collection source=%s ticker=%s status=failure error=%s",
                        connector.name,
                        ticker,
                        message,
                    )
                    events.append(CollectionEvent(
                        source=connector.name,
                        ticker=ticker,
                        started_at=started_at,
                        finished_at=datetime.now(timezone.utc),
                        status="failure",
                        records_read=0,
                        records_written=0,
                        records_inserted=0,
                        records_updated=0,
                        duplicate_records=0,
                        error_message=message,
                        market=request.market_for(ticker),
                        requested_start_date=request.start_date,
                        requested_end_date=request.end_date,
                        effective_start_date=ticker_start_date,
                        effective_end_date=request.end_date,
                        coverage_kind=self._coverage_kind(
                            connector,
                            request.start_date,
                            ticker_start_date,
                        ),
                        initial_backfill=self._initial_backfill,
                    ))
                    breaker.record_failure(connector.name)

        self._last_failures = tuple(failures)
        self._last_save_result = save_result
        self._last_events = tuple(events)
        return items

    def _filter_collected(
        self,
        items: Sequence[InformationItem],
    ) -> List[InformationItem]:
        """Apply the configured pre-persistence gate, if any.

        Exceptions intentionally propagate into the surrounding per-source or
        per-ticker collection handler.  This makes a relevance-model outage a
        visible collection failure instead of silently storing unreviewed news
        or community posts.
        """
        collected = list(items)
        if not collected or self._item_filter is None:
            return collected
        return self._item_filter.filter(collected)

    @staticmethod
    def _connector_failure_details(
        connector: SourceConnector,
    ) -> Tuple[dict, ...]:
        details = []
        for detail in tuple(
            getattr(connector, "last_failure_details", ()) or ()
        ):
            if not isinstance(detail, dict) and not hasattr(detail, "get"):
                continue
            message = str(detail.get("message") or "connector feed failed")
            details.append({
                "feed": str(detail.get("feed") or "") or None,
                "url": str(detail.get("url") or "") or None,
                "message": message,
            })
        return tuple(details)

    @staticmethod
    def _format_failure_detail(detail: dict) -> str:
        prefix = f"feed={detail.get('feed')}" if detail.get("feed") else "feed"
        if detail.get("url"):
            prefix += f" url={detail['url']}"
        return f"{prefix}: {detail['message']}"

    @staticmethod
    def _connector_error_for_ticker(
        connector: SourceConnector,
        ticker: str,
    ) -> Optional[str]:
        """Return a connector-reported per-ticker error after an empty result."""
        reported = tuple(getattr(connector, "last_errors", ()) or ())
        for error in reported:
            if isinstance(error, (tuple, list)) and len(error) >= 2:
                if str(error[0]).strip().upper() == ticker.strip().upper():
                    return str(error[1]) or "connector reported a failure"
                continue
            error_ticker = str(getattr(error, "ticker", "") or "")
            if error_ticker.strip().upper() == ticker.strip().upper():
                return str(getattr(error, "message", "") or error)
        if len(reported) == 1:
            error = reported[0]
            if isinstance(error, (tuple, list)) and len(error) >= 2:
                return str(error[1]) or "connector reported a failure"
            return str(getattr(error, "message", "") or error)
        return None

    @staticmethod
    def _clamped_start_date(
        connector: SourceConnector,
        start_date: date,
        end_date: date,
    ) -> date:
        """Limit a connector's lookback window when it declares a maximum."""
        max_lookback = getattr(connector, "max_lookback_days", None)
        if max_lookback is None:
            return start_date
        minimum_start = end_date - timedelta(days=int(max_lookback))
        return start_date if start_date >= minimum_start else minimum_start

    @staticmethod
    def _coverage_kind(
        connector: SourceConnector,
        requested_start: date,
        effective_start: date,
    ) -> str:
        declared = str(getattr(connector, "coverage_kind", "") or "")
        if declared in {
            "complete_window", "bounded_window", "feed_snapshot", "unknown"
        }:
            return declared
        if effective_start > requested_start:
            return "bounded_window"
        return "unknown"
