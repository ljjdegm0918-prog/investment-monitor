"""Free TRQ news connectors (market=trq only).

Yahoo Finance has no Turquoise-specific symbol suffix (Yahoo quotes
primary listings, not the TRQX/TQEX books), so no ``yahoo_trq``
connector exists. The Google News connector is the wired free source for
Turquoise companies.
"""

from .google.client import (
    GoogleTrqNewsClient,
    GoogleTrqNewsDataError,
    GoogleTrqNewsError,
    GoogleTrqNewsRequestError,
)
from .google.connector import GoogleTrqNewsConnector

__all__ = [
    "GoogleTrqNewsClient",
    "GoogleTrqNewsConnector",
    "GoogleTrqNewsDataError",
    "GoogleTrqNewsError",
    "GoogleTrqNewsRequestError",
]
