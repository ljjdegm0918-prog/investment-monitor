"""Source-independent information collection."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
import logging
from typing import Iterable, List, Optional, Tuple

from .connectors.base import SourceConnector
from .models import CollectionRequest, InformationItem
from .repository import InformationRepository, SaveResult

LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True)
class CollectionFailure:
    """One source/ticker pair that failed while other work continued."""

    source: str
    ticker: str
    message: str


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


class CollectionPipeline:
    """Collect and persist each source/ticker pair independently."""

    def __init__(
        self,
        connectors: Iterable[SourceConnector],
        repository: Optional[InformationRepository] = None,
        logger: logging.Logger = LOGGER,
    ) -> None:
        self._connectors = tuple(connectors)
        self._repository = repository
        self._logger = logger
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

        for connector in self._connectors:
            for ticker in request.tickers:
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
                    collected = connector.collect(ticker_request)
                    per_ticker_save = SaveResult()
                    if collected and self._repository is not None:
                        per_ticker_save = self._repository.save(collected)
                    save_result = save_result + per_ticker_save
                    items.extend(collected)
                    if collected:
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
                        records_read=len(collected),
                        records_written=per_ticker_save.inserted + per_ticker_save.updated,
                        records_inserted=per_ticker_save.inserted,
                        records_updated=per_ticker_save.updated,
                        duplicate_records=per_ticker_save.updated,
                    ))
                except Exception as error:
                    message = str(error) or error.__class__.__name__
                    failures.append(
                        CollectionFailure(
                            source=connector.name,
                            ticker=ticker,
                            message=message,
                        )
                    )
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
                    ))

        self._last_failures = tuple(failures)
        self._last_save_result = save_result
        self._last_events = tuple(events)
        return items

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
