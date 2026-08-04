"""Connector implementations and their shared contract."""

from .base import ConnectorUnavailableError, SourceConnector
from .mock import MockConnector
from .mock_community import MockCommunityConnector
from ..sources.news import (
    FinnhubClient,
    FinnhubNewsConnector,
    FinnhubNewsDataError,
    FinnhubNewsError,
    FinnhubNewsRequestError,
)
from ..sources.sec import (
    SECClient,
    SECConfigurationError,
    SECConnector,
    SECDataError,
    SECError,
    SECRequestError,
    TickerCollectionFailure,
)

__all__ = [
    "ConnectorUnavailableError",
    "FinnhubClient",
    "FinnhubNewsConnector",
    "FinnhubNewsDataError",
    "FinnhubNewsError",
    "FinnhubNewsRequestError",
    "MockConnector",
    "MockCommunityConnector",
    "SECClient",
    "SECConfigurationError",
    "SECConnector",
    "SECDataError",
    "SECError",
    "SECRequestError",
    "SourceConnector",
    "TickerCollectionFailure",
]
