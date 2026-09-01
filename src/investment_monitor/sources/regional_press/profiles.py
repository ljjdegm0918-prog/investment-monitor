"""Reviewed first-party RSS profiles for major regional news publishers.

Every URL below is published on, or linked from, the publisher's own domain.
The connector consumes only feed-supplied metadata and links; it never fetches
article bodies or attempts to bypass subscriptions.  Venue-only markets such
as CXE/TRQ/EUX/EMF deliberately have no profile because they are not regions.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Tuple


@dataclass(frozen=True)
class RegionalPressProfile:
    """One reviewed publisher feed exposed as one logical source."""

    source: str
    label: str
    market: str
    publisher: str
    publisher_domain: str
    feed_urls: Tuple[str, ...]
    feed_scope: str
    timezone: str
    language: str
    article_domains: Tuple[str, ...] = ()
    license_note: str = "publisher_rss_metadata_and_links_only"


REGIONAL_PRESS_PROFILES = (
    RegionalPressProfile(
        "marketwatch_us",
        "MarketWatch (US)",
        "us",
        "MarketWatch",
        "marketwatch.com",
        ("https://feeds.content.dowjones.io/public/rss/mw_topstories",),
        "top_stories",
        "America/New_York",
        "en",
    ),
    RegionalPressProfile(
        "globe_mail_ca",
        "The Globe and Mail Business (CA)",
        "ca",
        "The Globe and Mail",
        "theglobeandmail.com",
        (
            "https://www.theglobeandmail.com/arc/outboundfeeds/rss/"
            "category/business/",
        ),
        "business",
        "America/Toronto",
        "en",
    ),
    RegionalPressProfile(
        "el_economista_mx",
        "El Economista (MX)",
        "mx",
        "El Economista",
        "eleconomista.com.mx",
        ("https://www.eleconomista.com.mx/rss/ultimas-noticias",),
        "latest_news",
        "America/Mexico_City",
        "es",
    ),
    RegionalPressProfile(
        "bbc_business_uk",
        "BBC News Business (UK)",
        "uk",
        "BBC News",
        "bbc.co.uk",
        ("https://feeds.bbci.co.uk/news/business/rss.xml",),
        "business",
        "Europe/London",
        "en",
        ("bbc.com",),
    ),
    RegionalPressProfile(
        "lemonde_economie_fr",
        "Le Monde Économie (FR)",
        "fr",
        "Le Monde",
        "lemonde.fr",
        ("https://www.lemonde.fr/economie/rss_full.xml",),
        "economy",
        "Europe/Paris",
        "fr",
    ),
    RegionalPressProfile(
        "ilsole24ore_finanza_it",
        "Il Sole 24 Ore Finanza (IT)",
        "it",
        "Il Sole 24 Ore",
        "ilsole24ore.com",
        ("https://www.ilsole24ore.com/rss/finanza.xml",),
        "finance",
        "Europe/Rome",
        "it",
    ),
    RegionalPressProfile(
        "cincodias_mercados_es",
        "Cinco Días Mercados (ES)",
        "es",
        "Cinco Días",
        "cincodias.elpais.com",
        (
            "https://feeds.elpais.com/mrss-s/list/ep/site/"
            "cincodias.elpais.com/section/mercados-financieros",
        ),
        "financial_markets",
        "Europe/Madrid",
        "es",
        ("elpais.com",),
    ),
    RegionalPressProfile(
        "nzz_news_ch",
        "NZZ (CH)",
        "ch",
        "Neue Zürcher Zeitung",
        "nzz.ch",
        ("https://www.nzz.ch/recent.rss",),
        "recent_news",
        "Europe/Zurich",
        "de",
    ),
    RegionalPressProfile(
        "diepresse_news_at",
        "Die Presse (AT)",
        "at",
        "Die Presse",
        "diepresse.com",
        ("https://www.diepresse.com/rss",),
        "latest_news",
        "Europe/Vienna",
        "de",
    ),
    RegionalPressProfile(
        "e24_finance_no",
        "E24 Børs og finans (NO)",
        "no",
        "E24",
        "e24.no",
        ("https://e24.no/rss2?seksjon=boers-og-finans",),
        "markets_and_finance",
        "Europe/Oslo",
        "no",
    ),
    RegionalPressProfile(
        "jornal_negocios_pt",
        "Jornal de Negócios (PT)",
        "pt",
        "Jornal de Negócios",
        "jornaldenegocios.pt",
        ("https://www.jornaldenegocios.pt/rss",),
        "business",
        "Europe/Lisbon",
        "pt",
    ),
    RegionalPressProfile(
        "dagens_industri_se",
        "Dagens industri (SE)",
        "se",
        "Dagens industri",
        "di.se",
        ("https://www.di.se/rss/",),
        "business",
        "Europe/Stockholm",
        "sv",
    ),
    RegionalPressProfile(
        "portfolio_hu",
        "Portfolio.hu (HU)",
        "hu",
        "Portfolio.hu",
        "portfolio.hu",
        ("https://www.portfolio.hu/rss/all.xml",),
        "all_news",
        "Europe/Budapest",
        "hu",
    ),
    RegionalPressProfile(
        "err_news_ee",
        "ERR (EE)",
        "ee",
        "Eesti Rahvusringhääling",
        "err.ee",
        ("https://www.err.ee/rss",),
        "all_news",
        "Europe/Tallinn",
        "et",
    ),
    RegionalPressProfile(
        "lsm_news_lv",
        "LSM (LV)",
        "lv",
        "Latvijas Sabiedriskais medijs",
        "lsm.lv",
        ("https://www.lsm.lv/rss/",),
        "all_news",
        "Europe/Riga",
        "lv",
    ),
    RegionalPressProfile(
        "lrt_business_lt",
        "LRT Verslas (LT)",
        "lt",
        "Lietuvos nacionalinis radijas ir televizija",
        "lrt.lt",
        ("https://www.lrt.lt/naujienos/verslas?rss=",),
        "business",
        "Europe/Vilnius",
        "lt",
    ),
    RegionalPressProfile(
        "hankyung_finance_kr",
        "Korea Economic Daily Finance (KR)",
        "kr",
        "The Korea Economic Daily",
        "hankyung.com",
        ("https://www.hankyung.com/feed/finance",),
        "finance",
        "Asia/Seoul",
        "ko",
    ),
    RegionalPressProfile(
        "business_times_sg",
        "The Business Times (SG)",
        "sg",
        "The Business Times",
        "businesstimes.com.sg",
        ("https://www.businesstimes.com.sg/rss/banking-finance",),
        "banking_and_finance",
        "Asia/Singapore",
        "en",
    ),
    RegionalPressProfile(
        "globes_news_il",
        "Globes (IL)",
        "il",
        "Globes",
        "globes.co.il",
        (
            "https://www.globes.co.il/WebService/Rss/RssFeeder.asmx/"
            "FeederNode?iID=942",
        ),
        "headlines",
        "Asia/Jerusalem",
        "en",
    ),
    RegionalPressProfile(
        "rthk_finance_hk",
        "RTHK Finance (HK)",
        "hk",
        "Radio Television Hong Kong",
        "rthk.hk",
        ("https://rthk.hk/rthk/news/rss/e_expressnews_efinance.xml",),
        "finance",
        "Asia/Hong_Kong",
        "en",
    ),
    RegionalPressProfile(
        "scmp_business_hk",
        "SCMP Business (HK)",
        "hk",
        "South China Morning Post",
        "scmp.com",
        ("https://www.scmp.com/rss/92/feed",),
        "business",
        "Asia/Hong_Kong",
        "en",
    ),
)


REGIONAL_PRESS_MARKETS = {
    profile.source: profile.market for profile in REGIONAL_PRESS_PROFILES
}
REGIONAL_PRESS_LABELS = {
    profile.source: profile.label for profile in REGIONAL_PRESS_PROFILES
}

_REGION_LABELS = {
    "us": "United States",
    "ca": "Canada",
    "mx": "Mexico",
    "uk": "United Kingdom",
    "fr": "France",
    "it": "Italy",
    "es": "Spain",
    "ch": "Switzerland",
    "at": "Austria",
    "no": "Norway",
    "pt": "Portugal",
    "se": "Sweden",
    "hu": "Hungary",
    "ee": "Estonia",
    "lv": "Latvia",
    "lt": "Lithuania",
    "kr": "Korea",
    "sg": "Singapore",
    "il": "Israel",
    "hk": "Hong Kong",
}
REGIONAL_PRESS_REGIONS = {
    profile.source: (_REGION_LABELS[profile.market],)
    for profile in REGIONAL_PRESS_PROFILES
}
