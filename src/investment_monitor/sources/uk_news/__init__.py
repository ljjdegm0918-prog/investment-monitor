"""Free UK news connectors (market=uk only)."""

from .yahoo.client import (
    YahooNewsClient,
    YahooNewsDataError,
    YahooNewsError,
    YahooNewsRequestError,
)
from .yahoo.connector import YahooNewsConnector

__all__ = [
    "YahooNewsClient",
    "YahooNewsConnector",
    "YahooNewsDataError",
    "YahooNewsError",
    "YahooNewsRequestError",
]
