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
from .sources.investegate import InvestegateConnector
from .sources.kind import KindConnector
from .sources.kr_news import (
    HankyungConnector,
    NaverNewsConnector,
    TheBellConnector,
)
from .sources.kr_news.google.connector import GoogleKrNewsConnector
from .sources.kr_news.yahoo.connector import YahooKrNewsConnector
from .sources.news import FinnhubNewsConnector
from .sources.sec import SECConnector
from .sources.uk_news import YahooNewsConnector
from .sources.uk_news.google.connector import GoogleUkNewsConnector
from .sources.ca_news import (
    GoogleCaNewsConnector,
    YahooCaNewsConnector,
)
from .sources.twse_material import TwseMaterialConnector
from .sources.tpex_material import TpexMaterialConnector
from .sources.tw_news import (
    GoogleTwNewsConnector,
    YahooTwNewsConnector,
)
from .sources.asx_announcements import AsxAnnouncementsConnector
from .sources.au_news import (
    GoogleAuNewsConnector,
    YahooAuNewsConnector,
)
from .sources.ceoca_ca import CeocaCaConnector
from .sources.hotcopper_au import HotCopperAuConnector
from .sources.stockhead_au import StockheadAuConnector
from .sources.lse_share_chat import LseShareChatConnector
from .sources.xueqiu import XueqiuConnector
from .sources.seeking_alpha import SeekingAlphaConnector
from .sources.yellowbrick import YellowbrickConnector
from .sources.substack import SubstackConnector
from .sources.x_community import XCommunityConnector
from .sources.vic import VicConnector
from .sources.amf_oam import AmfOamConnector
from .sources.fsma_stori import StoriConnector
from .sources.cnmv_hr import CnmvHrConnector
from .sources.bme_relevant_facts import BmeRelevantFactsConnector
from .sources.fr_news import (
    GoogleFrNewsConnector,
    YahooFrNewsConnector,
)
from .sources.de_news import (
    GoogleDeNewsConnector,
    YahooDeNewsConnector,
)
from .sources.hkexnews import HkexNewsConnector
from .sources.hkex_di import HkexDiConnector
from .sources.hk_news import YahooHkNewsConnector
from .sources.hk_news.google.connector import GoogleHkNewsConnector
from .sources.jp_news import (
    GoogleJpNewsConnector,
    YahooJpNewsConnector,
)
from .sources.us_news import (
    GoogleUsNewsConnector,
    YahooUsNewsConnector,
)
from .sources.tdnet import TDnetConnector
from .sources.edinet import EDINETConnector
from .sources.eqs_dgap import EqsDgapConnector
from .sources.eqs_nl import EqsNlConnector
from .sources.eqs_it import EqsItConnector
from .sources.nl_news import (
    GoogleNlNewsConnector,
    YahooNlNewsConnector,
)
from .sources.it_news import (
    GoogleItNewsConnector,
    YahooItNewsConnector,
)
from .sources.es_news import (
    GoogleEsNewsConnector,
    YahooEsNewsConnector,
)
from .sources.sg_news import (
    GoogleSgNewsConnector,
    YahooSgNewsConnector,
)
from .sources.be_news import (
    GoogleBeNewsConnector,
    YahooBeNewsConnector,
)
from .sources.eqs_ch import EqsChConnector
from .sources.ch_news import (
    GoogleChNewsConnector,
    YahooChNewsConnector,
)
from .sources.pl_news import (
    GooglePlNewsConnector,
    YahooPlNewsConnector,
)
from .sources.se_news import (
    GoogleSeNewsConnector,
    YahooSeNewsConnector,
)
from .sources.aq_news import (
    GoogleAqNewsConnector,
    YahooAqNewsConnector,
)
from .sources.cxe_news import GoogleCxeNewsConnector
from .sources.emf_news import GoogleEmfNewsConnector
from .sources.trq_news import GoogleTrqNewsConnector
from .sources.eux_news import GoogleEuxNewsConnector
from .sources.gpw_espi import GpwEspiConnector

ConnectorFactory = Callable[[], SourceConnector]

SOURCE_MARKETS = {
    "sec": "us", "news": "us",
    "dart": "kr", "kind": "kr", "naver_news": "kr",
    "hankyung": "kr", "thebell": "kr",
    "yahoo_kr": "kr", "google_news_kr": "kr",
    "companies_house": "uk", "investegate": "uk", "yahoo_uk": "uk",
    "google_news_uk": "uk", "lse_share_chat": "uk",
    "hkexnews": "hk", "hkex_di": "hk", "yahoo_hk": "hk",
    "google_news_hk": "hk", "xueqiu": frozenset({"cn", "hk"}),
    "yahoo_ca": "ca", "google_news_ca": "ca", "ceoca_ca": "ca",
    "sedar_plus": "ca", "cse_filings": "ca", "neo_filings": "ca",
    "twse_material": "tw", "tpex_material": "tw", "yahoo_tw": "tw",
    "google_news_tw": "tw",
    "asx_announcements": "au", "yahoo_au": "au", "google_news_au": "au",
    "hotcopper_au": "au", "stockhead_au": "au",
    "seeking_alpha": "us", "substack": "us", "yellowbrick": "us",
    "x_community": "us", "vic": "us",
    "yahoo_us": "us", "google_news_us": "us",
    "yahoo_jp": "jp", "google_news_jp": "jp",
    "amf_oam": "fr", "yahoo_fr": "fr", "google_news_fr": "fr",
    "eqs_dgap": "de", "de_community": "de", "yahoo_de": "de",
    "google_news_de": "de",
    "eqs_nl": "nl", "yahoo_nl": "nl", "google_news_nl": "nl",
    "eqs_it": "it", "yahoo_it": "it", "google_news_it": "it",
    "cnmv_hr": "es", "bme_relevant_facts": "es", "yahoo_es": "es",
    "google_news_es": "es",
    "sgx_announcements": "sg", "yahoo_sg": "sg", "google_news_sg": "sg",
    "fsma_stori": "be", "be_second_disclosure": "be", "yahoo_be": "be",
    "google_news_be": "be",
    "eqs_ch": "ch", "six_official_notices": "ch", "yahoo_ch": "ch",
    "google_news_ch": "ch",
    "gpw_espi": "pl", "yahoo_pl": "pl", "google_news_pl": "pl",
    "fi_oam": "se", "yahoo_se": "se", "google_news_se": "se",
    "tdnet_public_web": "jp", "edinet": "jp",
}


def relevant_sources_for_market(
    names: Iterable[str],
    market: str,
) -> Tuple[str, ...]:
    """Return sources scoped to this market, preserving custom connectors.

    Connectors in the built-in registry have an explicit market.  Unknown
    names keep the legacy all-market behavior so an injected/custom registry
    connector is not silently dropped from collection.
    """
    relevant = []
    for name in names:
        scope = SOURCE_MARKETS.get(str(name))
        if scope is None or scope == market:
            relevant.append(name)
        elif isinstance(scope, (tuple, list, set, frozenset)) and market in scope:
            relevant.append(name)
    return tuple(relevant)


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
    registry.register(GoogleUkNewsConnector.name, GoogleUkNewsConnector)
    registry.register(YahooHkNewsConnector.name, YahooHkNewsConnector)
    registry.register(GoogleHkNewsConnector.name, GoogleHkNewsConnector)
    registry.register(YahooKrNewsConnector.name, YahooKrNewsConnector)
    registry.register(GoogleKrNewsConnector.name, GoogleKrNewsConnector)
    registry.register(YahooJpNewsConnector.name, YahooJpNewsConnector)
    registry.register(GoogleJpNewsConnector.name, GoogleJpNewsConnector)
    registry.register(YahooUsNewsConnector.name, YahooUsNewsConnector)
    registry.register(GoogleUsNewsConnector.name, GoogleUsNewsConnector)
    registry.register(YahooCaNewsConnector.name, YahooCaNewsConnector)
    registry.register(GoogleCaNewsConnector.name, GoogleCaNewsConnector)
    registry.register(TwseMaterialConnector.name, TwseMaterialConnector)
    registry.register(TpexMaterialConnector.name, TpexMaterialConnector)
    registry.register(YahooTwNewsConnector.name, YahooTwNewsConnector)
    registry.register(GoogleTwNewsConnector.name, GoogleTwNewsConnector)
    registry.register(AsxAnnouncementsConnector.name, AsxAnnouncementsConnector)
    registry.register(YahooAuNewsConnector.name, YahooAuNewsConnector)
    registry.register(GoogleAuNewsConnector.name, GoogleAuNewsConnector)
    registry.register(CeocaCaConnector.name, CeocaCaConnector)
    registry.register(HotCopperAuConnector.name, HotCopperAuConnector)
    registry.register(StockheadAuConnector.name, StockheadAuConnector)
    registry.register(LseShareChatConnector.name, LseShareChatConnector)
    registry.register(
        XueqiuConnector.name,
        XueqiuConnector,
        secret_fields=XueqiuConnector.secret_fields,
    )
    registry.register(SeekingAlphaConnector.name, SeekingAlphaConnector)
    registry.register(YellowbrickConnector.name, YellowbrickConnector)
    registry.register(SubstackConnector.name, SubstackConnector)
    registry.register(
        XCommunityConnector.name,
        XCommunityConnector.from_environment,
        secret_fields=XCommunityConnector.secret_fields,
        configuration_error=XCommunityConnector.configuration_error,
    )
    registry.register(VicConnector.name, VicConnector)
    registry.register(AmfOamConnector.name, AmfOamConnector)
    registry.register(StoriConnector.name, StoriConnector)
    registry.register(CnmvHrConnector.name, CnmvHrConnector)
    registry.register(
        BmeRelevantFactsConnector.name,
        BmeRelevantFactsConnector,
    )
    registry.register(YahooFrNewsConnector.name, YahooFrNewsConnector)
    registry.register(GoogleFrNewsConnector.name, GoogleFrNewsConnector)
    registry.register(EqsDgapConnector.name, EqsDgapConnector)
    registry.register(EqsNlConnector.name, EqsNlConnector)
    registry.register(EqsItConnector.name, EqsItConnector)
    registry.register(YahooNlNewsConnector.name, YahooNlNewsConnector)
    registry.register(GoogleNlNewsConnector.name, GoogleNlNewsConnector)
    registry.register(YahooItNewsConnector.name, YahooItNewsConnector)
    registry.register(GoogleItNewsConnector.name, GoogleItNewsConnector)
    registry.register(YahooEsNewsConnector.name, YahooEsNewsConnector)
    registry.register(GoogleEsNewsConnector.name, GoogleEsNewsConnector)
    registry.register(YahooSgNewsConnector.name, YahooSgNewsConnector)
    registry.register(GoogleSgNewsConnector.name, GoogleSgNewsConnector)
    registry.register(YahooBeNewsConnector.name, YahooBeNewsConnector)
    registry.register(GoogleBeNewsConnector.name, GoogleBeNewsConnector)
    registry.register(EqsChConnector.name, EqsChConnector)
    registry.register(YahooChNewsConnector.name, YahooChNewsConnector)
    registry.register(GoogleChNewsConnector.name, GoogleChNewsConnector)
    registry.register(YahooPlNewsConnector.name, YahooPlNewsConnector)
    registry.register(GooglePlNewsConnector.name, GooglePlNewsConnector)
    registry.register(YahooSeNewsConnector.name, YahooSeNewsConnector)
    registry.register(GoogleSeNewsConnector.name, GoogleSeNewsConnector)
    registry.register(YahooAqNewsConnector.name, YahooAqNewsConnector)
    registry.register(GoogleAqNewsConnector.name, GoogleAqNewsConnector)
    registry.register(GoogleCxeNewsConnector.name, GoogleCxeNewsConnector)
    registry.register(GoogleEmfNewsConnector.name, GoogleEmfNewsConnector)
    registry.register(GoogleTrqNewsConnector.name, GoogleTrqNewsConnector)
    registry.register(GoogleEuxNewsConnector.name, GoogleEuxNewsConnector)
    registry.register(GpwEspiConnector.name, GpwEspiConnector)
    registry.register(YahooDeNewsConnector.name, YahooDeNewsConnector)
    registry.register(GoogleDeNewsConnector.name, GoogleDeNewsConnector)
    registry.register(
        TDnetConnector.name,
        TDnetConnector.from_environment,
        secret_fields=TDnetConnector.secret_fields,
        configuration_error=TDnetConnector.configuration_error,
    )
    registry.register(
        EDINETConnector.name,
        EDINETConnector.from_environment,
        secret_fields=EDINETConnector.secret_fields,
        configuration_error=EDINETConnector.configuration_error,
    )
    return registry
