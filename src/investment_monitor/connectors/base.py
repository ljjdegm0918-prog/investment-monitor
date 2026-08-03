"""The contract implemented by all information sources."""

from __future__ import annotations

from typing import List, Protocol, runtime_checkable

from ..models import CollectionRequest, InformationItem


@runtime_checkable
class SourceConnector(Protocol):
    """Anything with this shape can participate in collection."""

    name: str

    def collect(self, request: CollectionRequest) -> List[InformationItem]:
        """Collect and standardize items matching the request."""
        ...

