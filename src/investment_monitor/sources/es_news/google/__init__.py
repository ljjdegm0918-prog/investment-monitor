"""Google News ES connector (market=es only)."""

from .client import (
    GoogleEsNewsClient,
    GoogleEsNewsDataError,
    GoogleEsNewsError,
    GoogleEsNewsRequestError,
)
from .connector import GoogleEsNewsConnector

__all__ = [
    "GoogleEsNewsClient",
    "GoogleEsNewsConnector",
    "GoogleEsNewsDataError",
    "GoogleEsNewsError",
    "GoogleEsNewsRequestError",
]
