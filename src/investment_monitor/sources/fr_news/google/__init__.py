"""Google News FR connector."""

from .client import (
    GoogleFrNewsClient,
    GoogleFrNewsDataError,
    GoogleFrNewsError,
    GoogleFrNewsRequestError,
)
from .connector import GoogleFrNewsConnector

__all__ = [
    "GoogleFrNewsClient",
    "GoogleFrNewsConnector",
    "GoogleFrNewsDataError",
    "GoogleFrNewsError",
    "GoogleFrNewsRequestError",
]
