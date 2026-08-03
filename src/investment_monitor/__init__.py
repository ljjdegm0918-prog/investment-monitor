"""Public API for the investment monitoring foundation."""

from .application import (
    ConfiguredCollectionResult,
    WorkflowResult,
    run_configured_collection,
    run_ticker_collection,
    run_workflow,
)
from .config import (
    ALLOWED_LIST_TYPES,
    CollectionSettings,
    ConfigurationError,
    UniverseEntry,
    load_environment_file,
    load_settings,
    load_universe,
)
from .connectors.base import SourceConnector
from .connectors.mock import MockConnector
from .connectors.mock_community import MockCommunityConnector
from .sources.sec import (
    SECClient,
    SECConfigurationError,
    SECConnector,
    SECDataError,
    SECError,
    SECRequestError,
    TickerCollectionFailure,
)
from .models import CollectionRequest, InformationItem
from .pipeline import CollectionFailure, CollectionPipeline
from .registry import SourceRegistry, create_default_registry
from .repository import InformationRepository, SaveResult
from .report import ReportResult, generate_html_report
from .sqlite_repository import SQLiteInformationRepository

__all__ = [
    "ALLOWED_LIST_TYPES",
    "CollectionFailure",
    "CollectionPipeline",
    "CollectionRequest",
    "CollectionSettings",
    "ConfigurationError",
    "ConfiguredCollectionResult",
    "InformationRepository",
    "InformationItem",
    "MockConnector",
    "MockCommunityConnector",
    "SECClient",
    "SECConfigurationError",
    "SECConnector",
    "SECDataError",
    "SECError",
    "SECRequestError",
    "SourceConnector",
    "SourceRegistry",
    "SQLiteInformationRepository",
    "SaveResult",
    "TickerCollectionFailure",
    "UniverseEntry",
    "WorkflowResult",
    "create_default_registry",
    "load_settings",
    "load_environment_file",
    "load_universe",
    "generate_html_report",
    "run_configured_collection",
    "run_ticker_collection",
    "run_workflow",
    "ReportResult",
]
