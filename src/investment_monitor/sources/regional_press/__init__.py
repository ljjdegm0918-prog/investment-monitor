"""Authoritative regional publisher RSS connectors."""

from .client import (
    RegionalPressClient,
    RegionalPressDataError,
    RegionalPressError,
    RegionalPressRequestError,
)
from .connector import RegionalPressConnector
from .discovery import (
    PublisherDiscoveryClient,
    PublisherDiscoveryDataError,
    PublisherDiscoveryError,
    PublisherDiscoveryRequestError,
    RegionalPublisherDiscoveryConnector,
)
from .discovery_profiles import (
    PUBLISHER_DISCOVERY_PROFILES,
    PublisherDiscoveryProfile,
)
from .profiles import (
    REGIONAL_PRESS_LABELS,
    REGIONAL_PRESS_PROFILES,
    RegionalPressProfile,
)

__all__ = [
    "REGIONAL_PRESS_PROFILES",
    "REGIONAL_PRESS_LABELS",
    "PUBLISHER_DISCOVERY_PROFILES",
    "PublisherDiscoveryClient",
    "PublisherDiscoveryDataError",
    "PublisherDiscoveryError",
    "PublisherDiscoveryProfile",
    "PublisherDiscoveryRequestError",
    "RegionalPressClient",
    "RegionalPressConnector",
    "RegionalPressDataError",
    "RegionalPressError",
    "RegionalPressProfile",
    "RegionalPressRequestError",
    "RegionalPublisherDiscoveryConnector",
]
