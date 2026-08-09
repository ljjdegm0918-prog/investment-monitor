"""Free FR news connectors (market=fr only)."""

from .google.client import (
    GoogleFrNewsClient,
    GoogleFrNewsDataError,
    GoogleFrNewsError,
    GoogleFrNewsRequestError,
)
from .google.connector import GoogleFrNewsConnector
from .symbols import fr_yahoo_symbol
from .yahoo.client import (
    YahooFrNewsClient,
    YahooFrNewsDataError,
    YahooFrNewsError,
    YahooFrNewsRequestError,
)
from .yahoo.connector import YahooFrNewsConnector

__all__ = [
    "GoogleFrNewsClient",
    "GoogleFrNewsConnector",
    "GoogleFrNewsDataError",
    "GoogleFrNewsError",
    "GoogleFrNewsRequestError",
    "YahooFrNewsClient",
    "YahooFrNewsConnector",
    "YahooFrNewsDataError",
    "YahooFrNewsError",
    "YahooFrNewsRequestError",
    "fr_yahoo_symbol",
]
