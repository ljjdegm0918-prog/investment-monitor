"""Registration and loading of enabled source connectors."""

from __future__ import annotations

from typing import Callable, Dict, Iterable, List

from .connectors.base import SourceConnector
from .connectors.mock import MockConnector
from .connectors.mock_community import MockCommunityConnector
from .sources.sec import SECConnector

ConnectorFactory = Callable[[], SourceConnector]


class SourceRegistry:
    """Map configuration names to connector factories."""

    def __init__(self) -> None:
        self._factories: Dict[str, ConnectorFactory] = {}

    def register(self, name: str, factory: ConnectorFactory) -> None:
        """Register a connector factory under a unique configuration name."""
        if not name:
            raise ValueError("Connector name must not be empty.")
        if name in self._factories:
            raise ValueError(f"Connector already registered: {name}")
        self._factories[name] = factory

    def load_enabled(self, names: Iterable[str]) -> List[SourceConnector]:
        """Create only the connectors named in application configuration."""
        connectors: List[SourceConnector] = []
        for name in names:
            try:
                factory = self._factories[name]
            except KeyError as error:
                raise KeyError(f"Unknown connector: {name}") from error
            connectors.append(factory())
        return connectors


def create_default_registry() -> SourceRegistry:
    """Build the application's registry of connector implementations."""
    registry = SourceRegistry()
    registry.register(MockConnector.name, MockConnector)
    registry.register(MockCommunityConnector.name, MockCommunityConnector)
    registry.register(SECConnector.name, SECConnector.from_environment)
    return registry
