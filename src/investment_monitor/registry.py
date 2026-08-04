"""Registration and loading of enabled source connectors."""

from __future__ import annotations

from typing import Callable, Dict, Iterable, List, Optional, Tuple

from .connectors.base import ConnectorUnavailableError, SourceConnector
from .connectors.mock import MockConnector
from .connectors.mock_community import MockCommunityConnector
from .sources.news import FinnhubNewsConnector
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

    @property
    def registered_names(self) -> Tuple[str, ...]:
        """Return the names of all registered connector factories."""
        return tuple(sorted(self._factories))

    def load_enabled(
        self,
        names: Iterable[str],
        missing: Optional[List[str]] = None,
        unavailable: Optional[List[str]] = None,
    ) -> List[SourceConnector]:
        """Create connectors named in configuration; skip unimplemented names.

        A source declared in configuration but not yet implemented (for
        example news or research before their P1 connectors exist) is
        collected into ``missing`` when provided instead of aborting the
        whole pipeline. A source whose factory cannot build because of
        missing configuration (for example no API key) is collected into
        ``unavailable``.
        """
        connectors: List[SourceConnector] = []
        for name in names:
            factory = self._factories.get(name)
            if factory is None:
                if missing is not None:
                    missing.append(name)
                continue
            try:
                connectors.append(factory())
            except ConnectorUnavailableError:
                if unavailable is not None:
                    unavailable.append(name)
        return connectors

    def factory_for(self, name: str) -> Optional[ConnectorFactory]:
        """Return the factory registered under ``name``, if any."""
        return self._factories.get(name)


def create_default_registry() -> SourceRegistry:
    """Build the application's registry of connector implementations."""
    registry = SourceRegistry()
    registry.register(MockConnector.name, MockConnector)
    registry.register(MockCommunityConnector.name, MockCommunityConnector)
    registry.register(FinnhubNewsConnector.name, FinnhubNewsConnector)
    registry.register(SECConnector.name, SECConnector.from_environment)
    return registry
