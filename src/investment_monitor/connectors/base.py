"""The contract implemented by all information sources."""

from __future__ import annotations

from dataclasses import dataclass
from typing import List, Protocol, runtime_checkable

from ..models import CollectionRequest, InformationItem


class ConnectorUnavailableError(ValueError):
    """Raised when a connector cannot be built (for example a missing API key).

    The registry treats this as "declared but not currently available":
    collection continues without the source and Data Sources shows a
    truthful Not connected state instead of a crash.
    """


@dataclass(frozen=True)
class SecretField:
    """One configurable credential a connector declares."""

    env: str
    label: str
    kind: str = "password"
    help: str = ""


@runtime_checkable
class SourceConnector(Protocol):
    """Anything with this shape can participate in collection."""

    name: str

    def collect(self, request: CollectionRequest) -> List[InformationItem]:
        """Collect and standardize items matching the request."""
        ...

