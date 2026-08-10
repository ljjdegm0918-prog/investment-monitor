"""Free EUX news connectors (market=eux only).

Yahoo Finance does not quote Eurex derivatives with a stable suffix
(live verified 2026-08-11), so no ``yahoo_eux`` connector exists. The
Google News connector is the wired free source for Eurex products.
"""

from .google.client import (
    GoogleEuxNewsClient,
    GoogleEuxNewsDataError,
    GoogleEuxNewsError,
    GoogleEuxNewsRequestError,
)
from .google.connector import GoogleEuxNewsConnector

__all__ = [
    "GoogleEuxNewsClient",
    "GoogleEuxNewsConnector",
    "GoogleEuxNewsDataError",
    "GoogleEuxNewsError",
    "GoogleEuxNewsRequestError",
]
