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
    SourceConfig,
    UniverseEntry,
    load_environment_file,
    load_settings,
    load_universe,
)
from .connectors.base import ConnectorUnavailableError, SourceConnector
from .connectors.mock import MockConnector
from .connectors.mock_community import MockCommunityConnector
from .sources.news import (
    FinnhubClient,
    FinnhubNewsConnector,
    FinnhubNewsDataError,
    FinnhubNewsError,
    FinnhubNewsRequestError,
)
from .sources.sec import (
    SECClient,
    SECConfigurationError,
    SECConnector,
    SECDataError,
    SECError,
    SECRequestError,
    TickerCollectionFailure,
)
from .models import (
    ALLOWED_MARKETS,
    CollectionRequest,
    InformationItem,
    MARKET_CN,
    MARKET_HK,
    MARKET_KR,
    MARKET_UNKNOWN,
    MARKET_US,
)
from .pipeline import CollectionFailure, CollectionPipeline
from .registry import SourceRegistry, create_default_registry
from .repository import InformationRepository, SaveResult
from .report import ReportResult, generate_html_report
from .sqlite_repository import SQLiteInformationRepository
from .web_repository import WebRepository

__all__ = [
    "ALLOWED_LIST_TYPES",
    "ALLOWED_MARKETS",
    "CollectionFailure",
    "CollectionPipeline",
    "CollectionRequest",
    "CollectionSettings",
    "ConfigurationError",
    "ConfiguredCollectionResult",
    "ConnectorUnavailableError",
    "FinnhubClient",
    "FinnhubNewsConnector",
    "FinnhubNewsDataError",
    "FinnhubNewsError",
    "FinnhubNewsRequestError",
    "InformationRepository",
    "InformationItem",
    "MARKET_CN",
    "MARKET_HK",
    "MARKET_KR",
    "MARKET_UNKNOWN",
    "MARKET_US",
    "MockConnector",
    "MockCommunityConnector",
    "SECClient",
    "SECConfigurationError",
    "SECConnector",
    "SECDataError",
    "SECError",
    "SECRequestError",
    "SourceConfig",
    "SourceConnector",
    "SourceRegistry",
    "SQLiteInformationRepository",
    "SaveResult",
    "TickerCollectionFailure",
    "UniverseEntry",
    "WorkflowResult",
    "WebRepository",
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
