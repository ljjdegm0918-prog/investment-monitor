"""Composition helpers for running collection from project configuration."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timezone
import logging
from pathlib import Path
from typing import Iterable, List, Mapping, Optional, Tuple

from .config import load_environment_file, load_settings, load_universe
from .content_relevance import content_relevance_filter_from_environment
from .models import CollectionRequest, InformationItem
from .pipeline import CollectionEvent, CollectionFailure, CollectionPipeline
from .registry import SOURCE_MARKETS, SourceRegistry, create_default_registry
from .report import ReportResult, generate_html_report
from .repository import SaveResult
from .sqlite_repository import SQLiteInformationRepository
from .web_repository import WebRepository

LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True)
class ConfiguredCollectionResult:
    items: Tuple[InformationItem, ...]
    failures: Tuple[CollectionFailure, ...]
    save_result: SaveResult
    database_path: Path
    stored_count: int
    events: Tuple[CollectionEvent, ...] = ()


@dataclass(frozen=True)
class WorkflowResult:
    collected_count: int
    save_result: SaveResult
    stored_count: int
    failure_count: int
    report: ReportResult


def _source_ticker_targets(
    source: str,
    tickers: Iterable[str],
    markets: Optional[Mapping[str, str]],
) -> Tuple[Tuple[str, str], ...]:
    """Return ticker/market targets to which a source actually applies."""
    declared_market = SOURCE_MARKETS.get(source)
    targets = []
    for ticker in tickers:
        market = str((markets or {}).get(ticker) or "unknown")
        if declared_market is None or market == declared_market:
            targets.append((ticker, market))
    return tuple(targets)


def run_configured_collection(
    *,
    universe_path: Path,
    settings_path: Path,
    start_date: date,
    end_date: date,
    registry: Optional[SourceRegistry] = None,
) -> ConfiguredCollectionResult:
    """Load config, run enabled sources, and persist standardized items."""
    universe = load_universe(universe_path)
    return run_ticker_collection(
        tickers=(entry.ticker for entry in universe),
        settings_path=settings_path,
        start_date=start_date,
        end_date=end_date,
        registry=registry,
        markets={entry.ticker: entry.market for entry in universe},
    )


def run_ticker_collection(
    *,
    tickers: Iterable[str],
    settings_path: Path,
    start_date: date,
    end_date: date,
    registry: Optional[SourceRegistry] = None,
    markets: Optional[Mapping[str, str]] = None,
    sources: Optional[Iterable[str]] = None,
    initial_backfill: bool = False,
) -> ConfiguredCollectionResult:
    """Collect an explicit ticker set, independent of the initial universe CSV."""
    normalized_tickers = tuple(
        dict.fromkeys(ticker.strip().upper() for ticker in tickers if ticker.strip())
    )
    if not normalized_tickers:
        raise ValueError("At least one ticker is required for collection.")
    load_environment_file(settings_path.parent.parent / ".env")
    settings = load_settings(settings_path)
    active_registry = registry or create_default_registry()
    missing_sources: List[str] = []
    unavailable_sources: List[str] = []
    requested_sources = (
        None
        if sources is None
        else frozenset(str(value) for value in sources)
    )
    selected_sources = tuple(
        source
        for source in settings.enabled_sources
        if requested_sources is None or source in requested_sources
    )
    connectors = active_registry.load_enabled(
        selected_sources,
        missing=missing_sources,
        unavailable=unavailable_sources,
    )
    for missing_source in missing_sources:
        LOGGER.warning(
            "Source declared in settings but not implemented; skipped: %s",
            missing_source,
        )
    for unavailable_source in unavailable_sources:
        LOGGER.warning(
            "Source declared in settings but unavailable (missing "
            "configuration); skipped: %s",
            unavailable_source,
        )
    repository = SQLiteInformationRepository(settings.database_path)
    pipeline = CollectionPipeline(
        connectors,
        repository=repository,
        initial_backfill=initial_backfill,
        source_markets=SOURCE_MARKETS,
        item_filter=content_relevance_filter_from_environment(),
    )
    items = pipeline.collect(
        CollectionRequest(
            tickers=normalized_tickers,
            start_date=start_date,
            end_date=end_date,
            markets=dict(markets or {}),
        )
    )
    unavailable_events: List[CollectionEvent] = []
    unavailable_failures: List[CollectionFailure] = []
    finished_at = datetime.now(timezone.utc)
    unavailable_reasons = tuple(
        (source, "source is not implemented")
        for source in missing_sources
    ) + tuple(
        (source, "source is unavailable or missing configuration")
        for source in unavailable_sources
    )
    for source, reason in unavailable_reasons:
        message = f"{reason}: {source}"
        for ticker, market in _source_ticker_targets(
            source,
            normalized_tickers,
            markets,
        ):
            unavailable_failures.append(CollectionFailure(
                source=source,
                ticker=ticker,
                message=message,
            ))
            unavailable_events.append(CollectionEvent(
                source=source,
                ticker=ticker,
                started_at=finished_at,
                finished_at=finished_at,
                status="failure",
                records_read=0,
                records_written=0,
                records_inserted=0,
                records_updated=0,
                duplicate_records=0,
                error_message=message,
                market=market,
                requested_start_date=start_date,
                requested_end_date=end_date,
                effective_start_date=start_date,
                effective_end_date=end_date,
                coverage_kind="unknown",
                initial_backfill=initial_backfill,
            ))
    events = pipeline.last_events + tuple(unavailable_events)
    failures = pipeline.last_failures + tuple(unavailable_failures)
    source_wide_state_targets = {
        connector.name: _source_ticker_targets(
            connector.name,
            normalized_tickers,
            markets,
        )
        for connector in connectors
        if bool(getattr(connector, "source_wide_collection", False))
    }
    WebRepository(
        settings.database_path,
        allowed_sources=settings.enabled_sources,
    ).record_collection_events(
        events,
        state_targets=source_wide_state_targets,
    )
    return ConfiguredCollectionResult(
        items=tuple(items),
        failures=failures,
        save_result=pipeline.last_save_result,
        database_path=settings.database_path,
        stored_count=repository.count(),
        events=events,
    )


def run_workflow(
    *,
    universe_path: Path,
    settings_path: Path,
    start_date: date,
    end_date: date,
    output_path: Path,
    registry: Optional[SourceRegistry] = None,
) -> WorkflowResult:
    """Run configuration, collection, persistence, and static reporting."""
    universe = load_universe(universe_path)
    load_environment_file(settings_path.parent.parent / ".env")
    settings = load_settings(settings_path)
    active_registry = registry or create_default_registry()
    missing_sources: List[str] = []
    unavailable_sources: List[str] = []
    connectors = active_registry.load_enabled(
        settings.enabled_sources,
        missing=missing_sources,
        unavailable=unavailable_sources,
    )
    for missing_source in missing_sources:
        LOGGER.warning(
            "Source declared in settings but not implemented; skipped: %s",
            missing_source,
        )
    for unavailable_source in unavailable_sources:
        LOGGER.warning(
            "Source declared in settings but unavailable (missing "
            "configuration); skipped: %s",
            unavailable_source,
        )
    repository = SQLiteInformationRepository(settings.database_path)
    pipeline = CollectionPipeline(
        connectors,
        repository=repository,
        source_markets=SOURCE_MARKETS,
        item_filter=content_relevance_filter_from_environment(),
    )
    items = pipeline.collect(
        CollectionRequest(
            tickers=tuple(entry.ticker for entry in universe),
            start_date=start_date,
            end_date=end_date,
            markets={entry.ticker: entry.market for entry in universe},
        )
    )
    WebRepository(settings.database_path, allowed_sources=settings.enabled_sources).record_collection_events(
        pipeline.last_events
    )
    report = generate_html_report(
        repository=repository,
        universe=universe,
        enabled_sources=settings.enabled_sources,
        start_date=start_date,
        end_date=end_date,
        failures=pipeline.last_failures,
        output_path=output_path,
    )
    return WorkflowResult(
        collected_count=len(items),
        save_result=pipeline.last_save_result,
        stored_count=repository.count(),
        failure_count=len(pipeline.last_failures),
        report=report,
    )
