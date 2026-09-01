"""Publisher-scoped discovery profiles for regions without usable direct RSS.

These profiles do not pretend that Google News is the publisher's API.  They
use a public Google News RSS search restricted to an reviewed publisher domain,
verify the RSS ``source`` domain, and retain only discovery metadata and the
Google News link.  Article bodies and paywalled pages are never fetched.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Tuple


@dataclass(frozen=True)
class PublisherDiscoveryProfile:
    """One authoritative publisher discovered through a site-scoped RSS query."""

    source: str
    label: str
    market: str
    publisher: str
    publisher_domains: Tuple[str, ...]
    query_domain: str
    hl: str
    gl: str
    ceid: str
    timezone: str
    language: str
    access_note: str = "google_news_site_scoped_metadata_only"


PUBLISHER_DISCOVERY_PROFILES = (
    PublisherDiscoveryProfile(
        "caixin_via_google_cn",
        "Caixin via Google News (CN)",
        "cn",
        "Caixin",
        ("caixin.com",),
        "caixin.com",
        "zh-CN",
        "CN",
        "CN:zh-Hans",
        "Asia/Shanghai",
        "zh-CN",
    ),
    PublisherDiscoveryProfile(
        "nikkei_via_google_jp",
        "Nikkei via Google News (JP)",
        "jp",
        "Nikkei",
        ("nikkei.com",),
        "nikkei.com",
        "ja",
        "JP",
        "JP:ja",
        "Asia/Tokyo",
        "ja",
    ),
    PublisherDiscoveryProfile(
        "cna_via_google_tw",
        "CNA Finance via Google News (TW)",
        "tw",
        "Central News Agency",
        ("cna.com.tw",),
        "cna.com.tw",
        "zh-TW",
        "TW",
        "TW:zh-Hant",
        "Asia/Taipei",
        "zh-TW",
    ),
    PublisherDiscoveryProfile(
        "afr_via_google_au",
        "Australian Financial Review via Google News (AU)",
        "au",
        "Australian Financial Review",
        ("afr.com",),
        "afr.com",
        "en-AU",
        "AU",
        "AU:en",
        "Australia/Sydney",
        "en",
    ),
    PublisherDiscoveryProfile(
        "business_standard_via_google_in",
        "Business Standard via Google News (IN)",
        "in",
        "Business Standard",
        ("business-standard.com",),
        "business-standard.com",
        "en-IN",
        "IN",
        "IN:en",
        "Asia/Kolkata",
        "en",
    ),
    PublisherDiscoveryProfile(
        "de_tijd_via_google_be",
        "De Tijd via Google News (BE)",
        "be",
        "De Tijd",
        ("tijd.be",),
        "tijd.be",
        "nl",
        "BE",
        "BE:nl",
        "Europe/Brussels",
        "nl",
    ),
    PublisherDiscoveryProfile(
        "handelsblatt_via_google_de",
        "Handelsblatt via Google News (DE)",
        "de",
        "Handelsblatt",
        ("handelsblatt.com",),
        "handelsblatt.com",
        "de",
        "DE",
        "DE:de",
        "Europe/Berlin",
        "de",
    ),
    PublisherDiscoveryProfile(
        "fd_via_google_nl",
        "Het Financieele Dagblad via Google News (NL)",
        "nl",
        "Het Financieele Dagblad",
        ("fd.nl",),
        "fd.nl",
        "nl",
        "NL",
        "NL:nl",
        "Europe/Amsterdam",
        "nl",
    ),
    PublisherDiscoveryProfile(
        "puls_biznesu_via_google_pl",
        "Puls Biznesu via Google News (PL)",
        "pl",
        "Puls Biznesu",
        ("pb.pl",),
        "pb.pl",
        "pl",
        "PL",
        "PL:pl",
        "Europe/Warsaw",
        "pl",
    ),
)


PUBLISHER_DISCOVERY_MARKETS = {
    profile.source: profile.market for profile in PUBLISHER_DISCOVERY_PROFILES
}
PUBLISHER_DISCOVERY_LABELS = {
    profile.source: profile.label for profile in PUBLISHER_DISCOVERY_PROFILES
}

_REGION_LABELS = {
    "cn": "China",
    "jp": "Japan",
    "tw": "Taiwan",
    "au": "Australia",
    "in": "India",
    "be": "Belgium",
    "de": "Germany",
    "nl": "Netherlands",
    "pl": "Poland",
}
PUBLISHER_DISCOVERY_REGIONS = {
    profile.source: (_REGION_LABELS[profile.market],)
    for profile in PUBLISHER_DISCOVERY_PROFILES
}
