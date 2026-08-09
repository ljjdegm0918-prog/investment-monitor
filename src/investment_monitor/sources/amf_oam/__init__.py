"""AMF OAM regulatory disclosures connector (market=fr)."""

from .client import (
    AmfOamClient,
    AmfOamDataError,
    AmfOamError,
    AmfOamRequestError,
)
from .connector import AmfOamConnector
from .matcher import AmfOamCompanyMatcher, company_names_match

__all__ = [
    "AmfOamClient",
    "AmfOamCompanyMatcher",
    "AmfOamConnector",
    "AmfOamDataError",
    "AmfOamError",
    "AmfOamRequestError",
    "company_names_match",
]
