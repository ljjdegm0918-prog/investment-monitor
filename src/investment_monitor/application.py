"""Composition helpers for running collection from project configuration."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Iterable, Optional, Tuple

from .config import load_environment_file, load_settings, load_universe
from .models import CollectionRequest, InformationItem
from .pipeline import CollectionFailure, CollectionPipeline
from .registry import SourceRegistry, create_default_registry
from .report import ReportResult, generate_html_report
from .repository import SaveResult
from .sqlite_repository import SQLiteInformationRepository
from .web_repository import WebRepository


@dataclass(frozen=True)
class ConfiguredCollectionResult:
    items: Tuple[InformationItem, ...]
    failures: Tuple[CollectionFailure, ...]
    save_result: SaveResult
    database_path: Path
    stored_count: int


@dataclass(frozen=True)
class WorkflowResult:
    collected_count: int
    save_result: SaveResult
    stored_count: int
    failure_count: int
    report: ReportResult


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
    )


def run_ticker_collection(
    *,
    tickers: Iterable[str],
    settings_path: Path,
    start_date: date,
    end_date: date,
    registry: Optional[SourceRegistry] = None,
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
    connectors = active_registry.load_enabled(settings.enabled_sources)
    repository = SQLiteInformationRepository(settings.database_path)
    pipeline = CollectionPipeline(connectors, repository=repository)
    items = pipeline.collect(
        CollectionRequest(
            tickers=normalized_tickers,
            start_date=start_date,
            end_date=end_date,
        )
    )
    WebRepository(settings.database_path, allowed_sources=settings.enabled_sources).record_collection_events(
        pipeline.last_events
    )
    return ConfiguredCollectionResult(
        items=tuple(items),
        failures=pipeline.last_failures,
        save_result=pipeline.last_save_result,
        database_path=settings.database_path,
        stored_count=repository.count(),
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
    connectors = active_registry.load_enabled(settings.enabled_sources)
    repository = SQLiteInformationRepository(settings.database_path)
    pipeline = CollectionPipeline(connectors, repository=repository)
    items = pipeline.collect(
        CollectionRequest(
            tickers=tuple(entry.ticker for entry in universe),
            start_date=start_date,
            end_date=end_date,
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
