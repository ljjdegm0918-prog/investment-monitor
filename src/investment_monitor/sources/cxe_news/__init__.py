"""Free CXE news connectors (market=cxe only).

There is no Yahoo Finance suffix for Cboe Europe symbols (live verified
2026-08-10: Yahoo covers primary listings, not the BXE/CXE books), so no
``yahoo_cxe`` connector exists. The Google News connector is the wired
free source for Cboe Europe companies.
"""

from .google.client import (
    GoogleCxeNewsClient,
    GoogleCxeNewsDataError,
    GoogleCxeNewsError,
    GoogleCxeNewsRequestError,
)
from .google.connector import GoogleCxeNewsConnector

__all__ = [
    "GoogleCxeNewsClient",
    "GoogleCxeNewsConnector",
    "GoogleCxeNewsDataError",
    "GoogleCxeNewsError",
    "GoogleCxeNewsRequestError",
]
