"""Authoritative regional publisher RSS connectors."""

from .client import (
    RegionalPressClient,
    RegionalPressDataError,
    RegionalPressError,
    RegionalPressRequestError,
)
from .connector import RegionalPressConnector
from .profiles import (
    REGIONAL_PRESS_LABELS,
    REGIONAL_PRESS_PROFILES,
    RegionalPressProfile,
)

__all__ = [
    "REGIONAL_PRESS_PROFILES",
    "REGIONAL_PRESS_LABELS",
    "RegionalPressClient",
    "RegionalPressConnector",
    "RegionalPressDataError",
    "RegionalPressError",
    "RegionalPressProfile",
    "RegionalPressRequestError",
]
