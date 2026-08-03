"""Connector implementations and their shared contract."""

from .base import SourceConnector
from .mock import MockConnector
from .mock_community import MockCommunityConnector
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
