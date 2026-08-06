"""Registration and loading of enabled source connectors."""

from __future__ import annotations

from typing import Callable, Dict, Iterable, List, Optional, Tuple

from .connectors.base import (
    ConnectorUnavailableError,
    SecretField,
    SourceConnector,
)
from .connectors.mock import MockConnector
from .connectors.mock_community import MockCommunityConnector
from .sources.companies_house import CompaniesHouseConnector
from .sources.dart import DARTConnector
from .sources.hk_news import YahooHkNewsConnector
from .sources.hkex_di import HkexDiConnector
from .sources.hkexnews import HkexNewsConnector
from .sources.investegate import InvestegateConnector
from .sources.kind import KindConnector
from .sources.kr_news import (
    HankyungConnector,
    NaverNewsConnector,
    TheBellConnector,
)
from .sources.news import FinnhubNewsConnector
from .sources.sec import SECConnector
from .sources.uk_news import YahooNewsConnector
from .sources.twse_material import TwseMaterialConnector
from .sources.tw_news import (
    GoogleTwNewsConnector,
    YahooTwNewsConnector,
)

ConnectorFactory = Callable[[], SourceConnector]


class SourceRegistry:
    """Map configuration names to connector factories."""

    def __init__(self) -> None:
        self._factories: Dict[str, ConnectorFactory] = {}
        self._secret_fields: Dict[str, Tuple[SecretField, ...]] = {}
        self._configuration_errors: Dict[str, Callable[[], Optional[str]]] = {}

    def register(
        self,
        name: str,
        factory: ConnectorFactory,
        secret_fields: Iterable[SecretField] = (),
        configuration_error: Optional[Callable[[], Optional[str]]] = None,
    ) -> None:
        """Register a connector factory and its credential declarations."""
        if not name:
            raise ValueError("Connector name must not be empty.")
        if name in self._factories:
            raise ValueError(f"Connector already registered: {name}")
        self._factories[name] = factory
        self._secret_fields[name] = tuple(secret_fields)
        if configuration_error is not None:
            self._configuration_errors[name] = configuration_error

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

    def secret_fields_for(self, name: str) -> Tuple[SecretField, ...]:
        """Return the credential fields declared by a registered source."""
        return self._secret_fields.get(name, ())

    def configuration_error_for(self, name: str) -> Optional[str]:
        """Return the declared configuration problem for a source, if any."""
        probe = self._configuration_errors.get(name)
        if probe is None:
            return None
        return probe()


def create_default_registry() -> SourceRegistry:
    """Build the application's registry of connector implementations."""
    registry = SourceRegistry()
    registry.register(MockConnector.name, MockConnector)
    registry.register(MockCommunityConnector.name, MockCommunityConnector)
    registry.register(
        FinnhubNewsConnector.name,
        FinnhubNewsConnector,
        secret_fields=FinnhubNewsConnector.secret_fields,
        configuration_error=FinnhubNewsConnector.configuration_error,
    )
    registry.register(
        SECConnector.name,
        SECConnector.from_environment,
        secret_fields=SECConnector.secret_fields,
        configuration_error=SECConnector.configuration_error,
    )
    registry.register(
        DARTConnector.name,
        DARTConnector,
        secret_fields=DARTConnector.secret_fields,
        configuration_error=DARTConnector.configuration_error,
    )
    registry.register(KindConnector.name, KindConnector)
    registry.register(
        CompaniesHouseConnector.name,
        CompaniesHouseConnector,
        secret_fields=CompaniesHouseConnector.secret_fields,
        configuration_error=CompaniesHouseConnector.configuration_error,
    )
    registry.register(InvestegateConnector.name, InvestegateConnector)
    registry.register(HkexNewsConnector.name, HkexNewsConnector)
    registry.register(HkexDiConnector.name, HkexDiConnector)
    registry.register(NaverNewsConnector.name, NaverNewsConnector)
    registry.register(HankyungConnector.name, HankyungConnector)
    registry.register(TheBellConnector.name, TheBellConnector)
    registry.register(YahooNewsConnector.name, YahooNewsConnector)
    registry.register(YahooHkNewsConnector.name, YahooHkNewsConnector)
    registry.register(TwseMaterialConnector.name, TwseMaterialConnector)
    registry.register(YahooTwNewsConnector.name, YahooTwNewsConnector)
    registry.register(GoogleTwNewsConnector.name, GoogleTwNewsConnector)
    return registry
