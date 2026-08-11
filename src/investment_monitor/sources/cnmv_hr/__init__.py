"""CNMV (Spain) official relevant-information RSS connector."""

from .client import (
    CnmvHrClient,
    CnmvHrDataError,
    CnmvHrError,
    CnmvHrFeedOutcome,
    CnmvHrFetchResult,
    CnmvHrRequestError,
)
from .connector import CnmvHrConnector
from .matcher import CnmvHrCompanyMatcher

__all__ = [
    "CnmvHrClient",
    "CnmvHrCompanyMatcher",
    "CnmvHrConnector",
    "CnmvHrDataError",
    "CnmvHrError",
    "CnmvHrFeedOutcome",
    "CnmvHrFetchResult",
    "CnmvHrRequestError",
]
