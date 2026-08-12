"""Free EMF news connectors (market=emf only).

Yahoo Finance has no stable symbol suffix for European mutual funds
(live verified 2026-08-10: a guessed Yahoo fund symbol returns an empty
feed), so no ``yahoo_emf`` connector exists. The Google News connector is
the wired free source for European funds.
"""

from .google.client import (
    GoogleEmfNewsClient,
    GoogleEmfNewsDataError,
    GoogleEmfNewsError,
    GoogleEmfNewsRequestError,
)
from .google.connector import GoogleEmfNewsConnector

__all__ = [
    "GoogleEmfNewsClient",
    "GoogleEmfNewsConnector",
    "GoogleEmfNewsDataError",
    "GoogleEmfNewsError",
    "GoogleEmfNewsRequestError",
]
