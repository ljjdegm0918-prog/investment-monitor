"""Cross-source soft dedupe for the information feed.

Dedupe is display-only and annotate-only: every database row stays in the
database AND in the feed list (1:1, totals untouched). Items that share a
robust identity key each get an "Also seen on …" annotation listing the other
members of their group. Keys prefer the 14-digit Korean disclosure receipt
number (rcept_no / acpt_no) shared by OpenDART and KIND. For UK, filings use
RNS ids (Investegate), Companies House transaction ids, or a same-source
title fallback; Companies House and Investegate are never paired by title
alone. For HK, hkexnews filings use NEWS_ID and hkex_di form serial;
hkexnews and hkex_di are never paired by title. News pairs on ticker + local
day + normalized title. For TW, TWSE and TPEx filings share no cross-source
identity, so their title fallback is source-scoped and the two boards are
never annotated against each other; same-source title fallback pairs on
ticker + Taipei day + normalized title. TW news (yahoo_tw / google_news_tw)
pairs across sources on ticker + Taipei day + normalized title. For CA, no
disclosure connector is wired (SEDAR+ A3 spike), so regulatory filings never
get a key and are never annotated; CA news (yahoo_ca / google_news_ca)
pairs across sources on ticker + Toronto day + normalized title. CA
community currently has a single source (`ceoca_ca`); soft-dedupe uses the
CEO.ca spiel id, or a source-scoped title fallback (ticker + Toronto day +
normalized title). With only one community source wired there is no
cross-source community pairing — same-source duplicate rows can still
annotate. For AU,
the only wired disclosure source is asx_announcements, which pairs on its
stable ASX document key, or on a source-scoped title fallback (ticker +
Sydney day + normalized title); AU news (yahoo_au / google_news_au) pairs
across sources on ticker + Sydney day + normalized title. AU community
currently has a single source (`hotcopper_au`); soft-dedupe uses the
HotCopper thread id, or a source-scoped title fallback (ticker + Sydney
day + normalized title). With only one community source wired there is no
cross-source "Also seen on" pairing for community — same-source duplicate
rows can still annotate. For FR,
the only wired disclosure source is amf_oam, which pairs on its stable OAM
document id, or on a source-scoped title fallback (ticker + Paris day +
normalized title); FR news (yahoo_fr / google_news_fr) pairs across sources
on ticker + Paris day + normalized title. For DE, the only wired disclosure
source is eqs_dgap, which pairs on its stable EQS news id, or on a
source-scoped title fallback (ticker + Berlin day + normalized title); DE
news (yahoo_de / google_news_de) pairs across sources on ticker + Berlin day
+ normalized title. For NL, the only wired disclosure source is eqs_nl,
which pairs on its stable EQS news id, or on a source-scoped title fallback
(ticker + Amsterdam day + normalized title); NL news (yahoo_nl /
google_news_nl) pairs across sources on ticker + Amsterdam day + normalized
title. For IT, the only wired disclosure source is eqs_it, which pairs on
its stable EQS news id, or on a source-scoped title fallback (ticker + Rome
day + normalized title); IT news (yahoo_it / google_news_it) pairs across
sources on ticker + Rome day + normalized title. For ES, cnmv_hr pairs on
its stable CNMV registration number and bme_relevant_facts pairs on its
stable CNMV registration number (``es:filing:cnmv`` / ``es:filing:bme``);
the two sources never pair against each other because their ids come from
independent APIs, and the title fallback is source-scoped (ticker + Madrid
day + normalized title). ES news (yahoo_es / google_news_es) pairs across
sources on ticker + Madrid day + normalized title. For SG, no disclosure
connector is wired (SGX A3 spike), so regulatory filings never get a key
and are never annotated; SG news (yahoo_sg / google_news_sg) pairs across
sources on ticker + Singapore day + normalized title.
For CH, the only wired disclosure source is eqs_ch, which pairs on its
stable EQS news id, or on a source-scoped title fallback (ticker + Zurich
day + normalized title); CH news (yahoo_ch / google_news_ch) pairs across
sources on ticker + Zurich day + normalized title.
For BE, the only wired disclosure source is fsma_stori, which pairs on its
stable FSMA STORI document id (``requiredReportingTopicId``), or on a
source-scoped title fallback (ticker + Brussels day + normalized title);
BE news (yahoo_be / google_news_be) pairs across sources on ticker +
Brussels day + normalized title.
For Hungary (hu) the disclosure primary chain is an honest stub (no
rows are produced), so no filing pairing exists yet; HU news
(yahoo_hu / google_news_hu) pairs across sources on ticker +
Budapest day + normalized title.

For Israel (il) the disclosure primary chain is an honest stub (no
rows are produced), so no filing pairing exists yet; IL news
(yahoo_il / google_news_il) pairs across sources on ticker +
Jerusalem day + normalized title.

For Mexico (mx) the disclosure primary chain is an honest stub (no
rows are produced), so no filing pairing exists yet; MX news
(yahoo_mx / google_news_mx) pairs across sources on ticker +
Mexico City day + normalized title.

For India (in), the NSE disclosure source pairs on its stable seq_id
and IN news (yahoo_in / google_news_in) pairs across sources on
ticker + Kolkata day + normalized title.

For Austria (at) the disclosure primary chain is an honest stub
(no rows are produced), so no filing pairing exists yet; AT news
(yahoo_at / google_news_at) pairs across sources on ticker + Vienna
day + normalized title.

For Norway (no) and Portugal (pt) the disclosure primary chains are
honest stubs (no rows are produced), so no filing pairing exists yet;
NO/PT news (yahoo_no / google_news_no, yahoo_pt / google_news_pt)
pairs across sources on ticker + Oslo/Lisbon day + normalized title.

For Baltic (ee/lv/lt), the only wired disclosure source is
nasdaq_baltic_news, which pairs on its stable disclosure id with a
source-scoped Tallinn-day title fallback; Baltic news (yahoo_ee /
google_news_ee, yahoo_lv / google_news_lv, yahoo_lt / google_news_lt)
pairs across sources on ticker + Tallinn day + normalized title.

For PL, the only wired disclosure source is gpw_espi, which pairs on its
stable GPW report id (``geru_id``), or on a source-scoped title fallback
(ticker + Warsaw day + normalized title); PL news (yahoo_pl /
google_news_pl) pairs across sources on ticker + Warsaw day + normalized
title.
For SE, no disclosure connector is wired (FI/Nasdaq/EQS A3 spike), so
regulatory filings never get a key and are never annotated; SE news
(yahoo_se / google_news_se) pairs across sources on ticker + Stockholm day
+ normalized title.
For AQ, no disclosure connector is wired (AQSE Vercel-challenge A3 spike),
so regulatory filings never get a key and are never annotated; AQ news
(yahoo_aq / google_news_aq) pairs across sources on ticker + London day +
normalized title (Europe/London, matching the AQSE publication timezone).
For CXE (Cboe Europe, first Alternative European Equities venue), no
disclosure connector is wired (MTF A3 spike), so regulatory filings never
get a key and are never annotated; CXE news (google_news_cxe only - no
Yahoo suffix exists for Cboe Europe) pairs on ticker + London day +
normalized title.
For EMF (European Mutual Funds / UCITS), no disclosure connector is wired
(ESMA A3 spike), so regulatory filings never get a key and are never
annotated; EMF news (google_news_emf only - no Yahoo suffix exists for
European funds) pairs on fund ISIN + Luxembourg day + normalized title.
For TRQ (Turquoise, second Alternative European Equities venue), no
disclosure connector is wired (MTF A3 spike), so regulatory filings never
get a key and are never annotated; TRQ news (google_news_trq only - no
Yahoo suffix exists for Turquoise) pairs on ticker + London day +
normalized title.
For EUX (Eurex Core derivatives), no disclosure connector is wired
(circular A3 spike), so regulatory filings never get a key and are never
annotated; EUX news (google_news_eux only - no Yahoo suffix exists for
Eurex derivatives) pairs on product code + Berlin day + normalized title.
For Substack (US newsletter platform, no structured ticker forum), the
only wired community source is `substack`, which pairs on its stable
post id (`external_id` = `substack-{guid}`), or on a source-scoped title
fallback (ticker + New York day + normalized title). With only one
Substack community source wired there is no cross-source community
pairing — same-source duplicate rows can still annotate. Substack
connector is a LIVE publication-whitelist RSS connector (spike
2026-08-11); category is newsletter article/news metadata, not
forum/discussion posts. No structured ticker binding: coverage depends
on whitelist quality and optional client-side keyword match quality.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple
from zoneinfo import ZoneInfo

KST = ZoneInfo("Asia/Seoul")
TOKYO = ZoneInfo("Asia/Tokyo")
LONDON = ZoneInfo("Europe/London")
HKT = ZoneInfo("Asia/Hong_Kong")
SHANGHAI = ZoneInfo("Asia/Shanghai")
TAIPEI = ZoneInfo("Asia/Taipei")
TORONTO = ZoneInfo("America/Toronto")
NEW_YORK = ZoneInfo("America/New_York")
SYDNEY = ZoneInfo("Australia/Sydney")
PARIS = ZoneInfo("Europe/Paris")
BERLIN = ZoneInfo("Europe/Berlin")
AMSTERDAM = ZoneInfo("Europe/Amsterdam")
ROME = ZoneInfo("Europe/Rome")
MADRID = ZoneInfo("Europe/Madrid")
SINGAPORE = ZoneInfo("Asia/Singapore")
ZURICH = ZoneInfo("Europe/Zurich")
WARSAW = ZoneInfo("Europe/Warsaw")
TALLINN = ZoneInfo("Europe/Tallinn")
OSLO = ZoneInfo("Europe/Oslo")
LISBON = ZoneInfo("Europe/Lisbon")
VIENNA = ZoneInfo("Europe/Vienna")
KOLKATA = ZoneInfo("Asia/Kolkata")
MEXICO_CITY = ZoneInfo("America/Mexico_City")
JERUSALEM = ZoneInfo("Asia/Jerusalem")
BUDAPEST = ZoneInfo("Europe/Budapest")
STOCKHOLM = ZoneInfo("Europe/Stockholm")
LUXEMBOURG = ZoneInfo("Europe/Luxembourg")
RECEIPT_LENGTH = 14
BRUSSELS = ZoneInfo("Europe/Brussels")

FILING_SOURCE_PRIORITY = {
    "ceoca_sedar": 19,
    "dart": 0,
    "investegate": 1,
    "companies_house": 2,
    "kind": 3,
    "sec": 4,
    "hkexnews": 5,
    "hkex_di": 6,
    "twse_material": 7,
    "tpex_material": 8,
    "asx_announcements": 9,
    "amf_oam": 10,
    "eqs_dgap": 11,
    "eqs_nl": 12,
    "eqs_it": 13,
    "cnmv_hr": 14,
    "bme_relevant_facts": 15,
    "fsma_stori": 16,
    "eqs_ch": 17,
    "gpw_espi": 18,
}
NEWS_SOURCE_PRIORITY = {
    "naver_news": 0,
    "yahoo_uk": 1,
    "news": 2,
    "hankyung": 3,
    "thebell": 4,
    "yahoo_hk": 5,
    "yahoo_tw": 6,
    "google_news_tw": 7,
    "yahoo_ca": 8,
    "google_news_ca": 9,
    "yahoo_au": 10,
    "google_news_au": 11,
    "yahoo_fr": 12,
    "google_news_fr": 13,
    "yahoo_de": 14,
    "google_news_de": 15,
    "yahoo_nl": 16,
    "google_news_nl": 17,
    "yahoo_it": 18,
    "google_news_it": 19,
    "yahoo_es": 20,
    "google_news_es": 21,
    "yahoo_sg": 22,
    "google_news_sg": 23,
    "yahoo_be": 24,
    "google_news_be": 25,
    "yahoo_ch": 26,
    "google_news_ch": 27,
    "yahoo_pl": 28,
    "google_news_pl": 29,
    "yahoo_se": 30,
    "google_news_se": 31,
    "nasdaq_baltic_news": 32,
    "yahoo_ee": 33,
    "google_news_ee": 34,
    "yahoo_lv": 35,
    "google_news_lv": 36,
    "yahoo_lt": 37,
    "google_news_lt": 38,
    "yahoo_no": 39,
    "google_news_no": 40,
    "yahoo_pt": 41,
    "google_news_pt": 42,
    "yahoo_at": 43,
    "google_news_at": 44,
    "nse_announcements": 45,
    "yahoo_in": 46,
    "google_news_in": 47,
    "bmv_relevant_events": 48,
    "yahoo_mx": 49,
    "google_news_mx": 50,
    "maya_announcements": 51,
    "yahoo_il": 52,
    "google_news_il": 53,
    "bse_hu_announcements": 54,
    "yahoo_hu": 55,
    "google_news_hu": 56,
    "yahoo_aq": 32,
    "google_news_aq": 33,
    "google_news_cxe": 34,
    "google_news_emf": 35,
    "google_news_trq": 36,
    "google_news_eux": 37,
    "google_news_uk": 38,
    "google_news_hk": 39,
    "yahoo_kr": 40,
    "google_news_kr": 41,
    "yahoo_jp": 42,
    "google_news_jp": 43,
    "yahoo_us": 44,
    "google_news_us": 45,
}
COMMUNITY_SOURCE_PRIORITY = {
    "ceoca_ca": 0,
    "hotcopper_au": 0,
    "stockhead_au": 0,
    "lse_share_chat": 0,
    "xueqiu": 0,
    "seeking_alpha": 0,
    "yellowbrick": 0,
    "substack": 0,
    "x_community": 0,
    "vic": 0,
}
SOURCE_DISPLAY_LABELS = {
    "ceoca_sedar": "CEO.ca SEDAR 文件镜像 (CA)",
    "dart": "OpenDART",
    "investegate": "Investegate",
    "companies_house": "Companies House",
    "kind": "KIND (KRX)",
    "sec": "SEC EDGAR",
    "naver_news": "Naver Finance",
    "news": "Finnhub News",
    "hankyung": "Hankyung",
    "thebell": "TheBell",
    "yahoo_uk": "Yahoo Finance UK",
    "yahoo_hk": "Yahoo Finance HK",
    "hkexnews": "HKEXnews (HKEX)",
    "hkex_di": "Disclosure of Interests (HKEX)",
    "twse_material": "TWSE OpenAPI (material)",
    "tpex_material": "TPEx OpenAPI (material)",
    "yahoo_tw": "Yahoo Finance TW",
    "google_news_tw": "Google News (TW)",
    "yahoo_ca": "Yahoo Finance CA",
    "google_news_ca": "Google News (CA)",
    "asx_announcements": "ASX announcements",
    "yahoo_au": "Yahoo Finance AU",
    "google_news_au": "Google News (AU)",
    "amf_oam": "AMF OAM",
    "yahoo_fr": "Yahoo Finance FR",
    "google_news_fr": "Google News (FR)",
    "eqs_dgap": "EQS News (DGAP)",
    "yahoo_de": "Yahoo Finance DE",
    "google_news_de": "Google News (DE)",
    "eqs_nl": "EQS News (NL)",
    "yahoo_nl": "Yahoo Finance NL",
    "google_news_nl": "Google News (NL)",
    "eqs_it": "EQS News (IT)",
    "yahoo_it": "Yahoo Finance IT",
    "google_news_it": "Google News (IT)",
    "cnmv_hr": "CNMV (hechos relevantes)",
    "bme_relevant_facts": "BME Relevant Facts",
    "yahoo_es": "Yahoo Finance ES",
    "google_news_es": "Google News (ES)",
    "yahoo_sg": "Yahoo Finance SG",
    "google_news_sg": "Google News (SG)",
    "fsma_stori": "FSMA STORI",
    "yahoo_be": "Yahoo Finance BE",
    "google_news_be": "Google News (BE)",
    "eqs_ch": "EQS News (CH)",
    "yahoo_ch": "Yahoo Finance CH",
    "google_news_ch": "Google News (CH)",
    "gpw_espi": "GPW ESPI/EBI",
    "yahoo_pl": "Yahoo Finance PL",
    "google_news_pl": "Google News (PL)",
    "yahoo_se": "Yahoo Finance SE",
    "google_news_se": "Google News (SE)",
    "nasdaq_baltic_news": "Nasdaq Baltic",
    "yahoo_ee": "Yahoo Finance EE",
    "google_news_ee": "Google News (EE)",
    "yahoo_lv": "Yahoo Finance LV",
    "google_news_lv": "Google News (LV)",
    "yahoo_lt": "Yahoo Finance LT",
    "google_news_lt": "Google News (LT)",
    "newsweb_no": "NewsWeb (Oslo Bors)",
    "euronext_lisbon_news": "Euronext Lisbon",
    "yahoo_no": "Yahoo Finance NO",
    "google_news_no": "Google News (NO)",
    "yahoo_pt": "Yahoo Finance PT",
    "google_news_pt": "Google News (PT)",
    "wiener_boerse_news": "Wiener Börse",
    "yahoo_at": "Yahoo Finance AT",
    "google_news_at": "Google News (AT)",
    "nse_announcements": "NSE announcements",
    "yahoo_in": "Yahoo Finance IN",
    "google_news_in": "Google News (IN)",
    "bmv_relevant_events": "BMV relevant events",
    "yahoo_mx": "Yahoo Finance MX",
    "google_news_mx": "Google News (MX)",
    "maya_announcements": "MAYA (TASE)",
    "yahoo_il": "Yahoo Finance IL",
    "google_news_il": "Google News (IL)",
    "bse_hu_announcements": "BSE (Budapest)",
    "yahoo_hu": "Yahoo Finance HU",
    "google_news_hu": "Google News (HU)",
    "yahoo_aq": "Yahoo Finance AQ",
    "google_news_aq": "Google News (AQ)",
    "google_news_cxe": "Google News (CXE)",
    "google_news_emf": "Google News (EMF)",
    "google_news_trq": "Google News (TRQ)",
    "google_news_eux": "Google News (EUX)",
    "google_news_uk": "Google News (UK)",
    "google_news_hk": "Google News (HK)",
    "yahoo_kr": "Yahoo Finance KR",
    "google_news_kr": "Google News (KR)",
    "yahoo_jp": "Yahoo Finance JP",
    "google_news_jp": "Google News (JP)",
    "yahoo_us": "Yahoo Finance US",
    "google_news_us": "Google News (US)",
    "ceoca_ca": "CEO.ca (CA)",
    "hotcopper_au": "HotCopper (AU)",
    "stockhead_au": "Stockhead (AU)",
    "lse_share_chat": "LSE Share Chat (UK)",
    "xueqiu": "Xueqiu (CN/HK)",
    "seeking_alpha": "Seeking Alpha (US)",
    "yellowbrick": "Yellowbrick Investing (US)",
    "substack": "Substack (US)",
    "x_community": "X (US)",
    "vic": "Value Investors Club (US)",
}

_FULLWIDTH_SPACE = "\u3000"
_NBSP = "\u00a0"
_TRAILING_ETC = re.compile(r"\s+등\s*$")
_US_NEWS_SOURCES = frozenset({"news", "yahoo_us", "google_news_us"})
_JP_NEWS_SOURCES = frozenset({"yahoo_jp", "google_news_jp"})
_KR_NEWS_SOURCES = frozenset(
    {
        "news",
        "naver_news",
        "hankyung",
        "thebell",
        "yahoo_kr",
        "google_news_kr",
    }
)


def dedupe_key(item: Mapping[str, Any]) -> Optional[str]:
    """Return a stable cross-source key, or None when not deduplicable."""
    market = str(item.get("market") or "")
    if market not in {
        "kr", "uk", "hk", "tw", "ca", "au", "fr", "de", "nl", "it", "es",
        "sg", "be", "ch", "pl", "se", "ee", "lv", "lt", "no", "pt", "at", "in", "mx", "il", "hu", "aq", "cxe", "emf", "trq", "eux",
        "cn", "us", "jp",
    }:
        return None
    source_type = str(item.get("source_type") or "")
    if source_type == "regulatory_filing":
        return _filing_key(item, market)
    if source_type == "news":
        return _news_key(item, market)
    if source_type == "community":
        return _community_key(item, market)
    return None


def annotate_feed_items(
    items: Sequence[Mapping[str, Any]],
    *,
    enabled: bool = True,
) -> List[Mapping[str, Any]]:
    """Keep every row and annotate cross-source duplicates as "also seen on".

    Soft dedupe never drops rows and never changes totals: rows sharing a
    ``dedupe_key`` each get ``also_seen_on`` / ``also_seen_on_labels`` for the
    other members of their group. Annotation is based on the raw rows of the
    current page only; the same key split across pages may not see each other
    (totals and page sizes stay correct either way).
    """
    if not enabled:
        return [dict(item) for item in items]

    groups: Dict[str, List[Mapping[str, Any]]] = {}
    for item in items:
        key = dedupe_key(item)
        if key is None:
            continue
        groups.setdefault(key, []).append(item)

    annotated: List[Mapping[str, Any]] = []
    for item in items:
        entry = dict(item)
        key = dedupe_key(item)
        if key is None:
            annotated.append(entry)
            continue
        group = groups[key]
        others = [other for other in group if other is not item]
        entry["dedupe_count"] = len(group)
        if others:
            entry["also_seen_on"] = [
                str(other["source"]) for other in others
            ]
            entry["also_seen_on_labels"] = [
                SOURCE_DISPLAY_LABELS.get(
                    str(other["source"]),
                    str(other["source"]),
                )
                for other in others
            ]
        annotated.append(entry)
    return annotated


def fold_feed_items(
    items: Sequence[Mapping[str, Any]],
    *,
    enabled: bool = True,
) -> List[Mapping[str, Any]]:
    """Deprecated alias for :func:`annotate_feed_items`.

    The old "fold to one primary" behavior is gone: every row is kept and
    duplicates are annotated instead of collapsed.
    """
    return annotate_feed_items(items, enabled=enabled)


def normalize_title(value: Any) -> str:
    """Normalize a title for fallback identity comparison."""
    text = str(value or "").replace(_FULLWIDTH_SPACE, " ").replace(
        _NBSP, " "
    )
    text = re.sub(r"\s+", " ", text).strip().lower()
    return _TRAILING_ETC.sub("", text)


def _filing_key(item: Mapping[str, Any], market: str) -> Optional[str]:
    if market == "us":
        # SEC-only filings; no cross-source filing pairing on the US feed.
        return None
    if market == "jp":
        # TDnet/EDINET pairing is source-scoped elsewhere; no cross-source
        # filing title pairing on the JP feed yet.
        return None
    if market == "kr":
        return _kr_filing_key(item)
    if market == "hk":
        return _hk_filing_key(item)
    if market == "tw":
        return _tw_filing_key(item)
    if market == "ca":
        # No CA disclosure connector is wired (SEDAR+ A3 spike); a stray
        # regulatory_filing row must never be cross-annotated.
        return None
    if market == "aq":
        # No AQ disclosure connector is wired (AQSE Vercel-challenge A3
        # spike); a stray regulatory_filing row must never be
        # cross-annotated.
        return None
    if market == "cxe":
        # No CXE disclosure connector is wired (MTF A3 spike); a stray
        # regulatory_filing row must never be cross-annotated.
        return None
    if market == "emf":
        # No EMF disclosure connector is wired (ESMA A3 spike); a stray
        # regulatory_filing row must never be cross-annotated.
        return None
    if market == "trq":
        # No TRQ disclosure connector is wired (MTF A3 spike); a stray
        # regulatory_filing row must never be cross-annotated.
        return None
    if market == "eux":
        # No EUX disclosure connector is wired (circular A3 spike); a
        # stray regulatory_filing row must never be cross-annotated.
        return None
    if market == "sg":
        # No SG disclosure connector is wired (SGX A3 spike); a stray
        # regulatory_filing row must never be cross-annotated.
        return None
    if market == "se":
        # No SE disclosure connector is wired (FI/Nasdaq/EQS A3 spike); a
        # stray regulatory_filing row must never be cross-annotated.
        return None
    if market == "ch":
        return _ch_filing_key(item)
    if market == "in":
        return _in_filing_key(item)
    if market == "mx":
        # Disclosure primary chain is an honest stub (no rows produced);
        # a stray filing row must never be cross-annotated.
        return None
    if market == "il":
        # Disclosure primary chain is an honest stub (no rows produced);
        # a stray filing row must never be cross-annotated.
        return None
    if market == "hu":
        # Disclosure primary chain is an honest stub (no rows produced);
        # a stray filing row must never be cross-annotated.
        return None
    if market == "at":
        # Disclosure primary chain is an honest stub (no rows produced);
        # a stray filing row must never be cross-annotated.
        return None
    if market in ("no", "pt"):
        # Disclosure primary chains are honest stubs (no rows produced);
        # a stray filing row must never be cross-annotated.
        return None
    if market in ("ee", "lv", "lt"):
        return _baltic_filing_key(item)
    if market == "pl":
        return _pl_filing_key(item)
    if market == "au":
        return _au_filing_key(item)
    if market == "fr":
        return _fr_filing_key(item)
    if market == "de":
        return _de_filing_key(item)
    if market == "nl":
        return _nl_filing_key(item)
    if market == "it":
        return _it_filing_key(item)
    if market == "es":
        return _es_filing_key(item)
    if market == "be":
        return _be_filing_key(item)
    return _uk_filing_key(item)


def _es_filing_key(item: Mapping[str, Any]) -> Optional[str]:
    """ES filings pair on a stable CNMV registration number, or a fallback.

    ``cnmv_hr`` and ``bme_relevant_facts`` both carry the CNMV registration
    number, but their ids come from two independent APIs (RSS vs BME JSON)
    and are never paired across sources: the primary key is prefixed with
    the source family. Without an id, the fallback is source-scoped
    (source + ticker + Madrid day + normalized title), so the two sources
    are never cross-annotated by title.
    """
    source = str(item.get("source") or "")
    metadata = item.get("raw_metadata") or {}
    document_id = str(
        metadata.get("document_id") or item.get("external_id") or ""
    ).strip()
    if document_id:
        prefix = (
            "cnmv"
            if source == "cnmv_hr"
            else "bme"
            if source == "bme_relevant_facts"
            else "es"
        )
        return f"es:filing:{prefix}:{document_id}"
    title = normalize_title(item.get("title"))
    day = _local_day(item, MADRID)
    if title and day:
        return (
            f"es:filing:title:{source}:"
            f"{item.get('ticker')}:{day}:{title}"
        )
    return None


def _ch_filing_key(item: Mapping[str, Any]) -> Optional[str]:
    """CH filings pair on the stable EQS news id, or a title fallback.

    ``eqs_ch`` is the only wired CH disclosure source; its news id
    (``external_id``) is the primary identity. Without one, the fallback is
    source-scoped (source + ticker + Zurich day + normalized title), so a
    hypothetical second CH disclosure source is never cross-annotated by
    title.
    """
    source = str(item.get("source") or "")
    document_id = str(item.get("external_id") or "").strip()
    if document_id:
        return f"ch:filing:eqs:{document_id}"
    title = normalize_title(item.get("title"))
    day = _local_day(item, ZURICH)
    if title and day:
        return (
            f"ch:filing:title:{source}:"
            f"{item.get('ticker')}:{day}:{title}"
        )
    return None


def _be_filing_key(item: Mapping[str, Any]) -> Optional[str]:
    """BE filings pair on the stable FSMA STORI document id, or a fallback.

    ``fsma_stori`` is the only wired BE disclosure source; its stable
    document id (``external_id`` = STORI ``requiredReportingTopicId``) is
    the primary identity. Without one, the fallback is source-scoped
    (source + ticker + Brussels day + normalized title), so a hypothetical
    second BE disclosure source is never cross-annotated by title.
    """
    source = str(item.get("source") or "")
    document_id = str(item.get("external_id") or "").strip()
    if document_id:
        return f"be:filing:stori:{document_id}"
    title = normalize_title(item.get("title"))
    day = _local_day(item, BRUSSELS)
    if title and day:
        return (
            f"be:filing:title:{source}:"
            f"{item.get('ticker')}:{day}:{title}"
        )
    return None


def _baltic_filing_key(item: Mapping[str, Any]) -> Optional[str]:
    """Baltic filings pair on the stable Nasdaq Baltic disclosure id.

    ``nasdaq_baltic_news`` is the only wired Baltic disclosure source; its
    ``external_id`` (``baltic:<disclosureId>``) is the primary identity.
    Without one, the fallback is source-scoped (source + ticker + Tallinn
    day + normalized title), so a hypothetical second Baltic disclosure
    source is never cross-annotated by title.
    """
    source = str(item.get("source") or "")
    document_id = str(item.get("external_id") or "").strip()
    if document_id:
        return f"{item.get('market')}:filing:baltic:{document_id}"
    title = normalize_title(item.get("title"))
    day = _local_day(item, TALLINN)
    if title and day:
        return (
            f"{item.get('market')}:filing:title:{source}:"
            f"{item.get('ticker')}:{day}:{title}"
        )
    return None


def _in_filing_key(item: Mapping[str, Any]) -> Optional[str]:
    """IN filings pair on the stable NSE seq_id, with a source-scoped
    Kolkata-day title fallback."""
    source = str(item.get("source") or "")
    document_id = str(item.get("external_id") or "").strip()
    if document_id:
        return f"in:filing:nse:{document_id}"
    title = normalize_title(item.get("title"))
    day = _local_day(item, KOLKATA)
    if title and day:
        return (
            f"in:filing:title:{source}:"
            f"{item.get('ticker')}:{day}:{title}"
        )
    return None


def _pl_filing_key(item: Mapping[str, Any]) -> Optional[str]:
    """PL filings pair on the stable GPW report id, or a title fallback.

    ``gpw_espi`` is the only wired PL disclosure source; its stable report
    id (``external_id`` = GPW ``geru_id``) is the primary identity. Without
    one, the fallback is source-scoped (source + ticker + Warsaw day +
    normalized title), so a hypothetical second PL disclosure source is
    never cross-annotated by title.
    """
    source = str(item.get("source") or "")
    document_id = str(item.get("external_id") or "").strip()
    if document_id:
        return f"pl:filing:gpw:{document_id}"
    title = normalize_title(item.get("title"))
    day = _local_day(item, WARSAW)
    if title and day:
        return (
            f"pl:filing:title:{source}:"
            f"{item.get('ticker')}:{day}:{title}"
        )
    return None


def _de_filing_key(item: Mapping[str, Any]) -> Optional[str]:
    """DE filings pair on the stable EQS news id, or a title fallback.

    ``eqs_dgap`` is the only wired DE disclosure source; its news id
    (``external_id``) is the primary identity. Without one, the fallback is
    source-scoped (source + ticker + Berlin day + normalized title).
    """
    source = str(item.get("source") or "")
    document_id = str(item.get("external_id") or "").strip()
    if document_id:
        return f"de:filing:eqs:{document_id}"
    title = normalize_title(item.get("title"))
    day = _local_day(item, BERLIN)
    if title and day:
        return (
            f"de:filing:title:{source}:"
            f"{item.get('ticker')}:{day}:{title}"
        )
    return None


def _nl_filing_key(item: Mapping[str, Any]) -> Optional[str]:
    """NL filings pair on the stable EQS news id, or a title fallback.

    ``eqs_nl`` is the only wired NL disclosure source; its news id
    (``external_id``) is the primary identity. Without one, the fallback is
    source-scoped (source + ticker + Amsterdam day + normalized title), so a
    hypothetical second NL disclosure source is never cross-annotated by
    title.
    """
    source = str(item.get("source") or "")
    document_id = str(item.get("external_id") or "").strip()
    if document_id:
        return f"nl:filing:eqs:{document_id}"
    title = normalize_title(item.get("title"))
    day = _local_day(item, AMSTERDAM)
    if title and day:
        return (
            f"nl:filing:title:{source}:"
            f"{item.get('ticker')}:{day}:{title}"
        )
    return None


def _it_filing_key(item: Mapping[str, Any]) -> Optional[str]:
    """IT filings pair on the stable EQS news id, or a title fallback.

    ``eqs_it`` is the only wired IT disclosure source; its news id
    (``external_id``) is the primary identity. Without one, the fallback is
    source-scoped (source + ticker + Rome day + normalized title), so a
    hypothetical second IT disclosure source is never cross-annotated by
    title.
    """
    source = str(item.get("source") or "")
    document_id = str(item.get("external_id") or "").strip()
    if document_id:
        return f"it:filing:eqs:{document_id}"
    title = normalize_title(item.get("title"))
    day = _local_day(item, ROME)
    if title and day:
        return (
            f"it:filing:title:{source}:"
            f"{item.get('ticker')}:{day}:{title}"
        )
    return None


def _fr_filing_key(item: Mapping[str, Any]) -> Optional[str]:
    """FR filings pair on the stable AMF OAM document id, or a fallback.

    ``amf_oam`` is the only wired FR disclosure source; its document id
    (``raw_metadata.document_id`` or ``external_id``) is the primary
    identity. Without one, the fallback is source-scoped (source + ticker +
    Paris day + normalized title), so a hypothetical second FR disclosure
    source is never cross-annotated by title.
    """
    source = str(item.get("source") or "")
    metadata = item.get("raw_metadata") or {}
    document_id = str(
        metadata.get("document_id") or item.get("external_id") or ""
    ).strip()
    if document_id:
        return f"fr:filing:oam:{document_id}"
    title = normalize_title(item.get("title"))
    day = _local_day(item, PARIS)
    if title and day:
        return (
            f"fr:filing:title:{source}:"
            f"{item.get('ticker')}:{day}:{title}"
        )
    return None


def _au_filing_key(item: Mapping[str, Any]) -> Optional[str]:
    """AU filings pair on the stable ASX document key, or a title fallback.

    ``asx_announcements`` is the only wired AU disclosure source; its
    document key (``raw_metadata.document_key`` or ``external_id``) is the
    primary identity. Without one, the fallback is source-scoped (source +
    ticker + Sydney day + normalized title), so a hypothetical second AU
    disclosure source is never cross-annotated by title.
    """
    source = str(item.get("source") or "")
    metadata = item.get("raw_metadata") or {}
    document_key = str(
        metadata.get("document_key") or item.get("external_id") or ""
    ).strip()
    if document_key:
        return f"au:filing:asx:{document_key}"
    title = normalize_title(item.get("title"))
    day = _local_day(item, SYDNEY)
    if title and day:
        return (
            f"au:filing:title:{source}:"
            f"{item.get('ticker')}:{day}:{title}"
        )
    return None


def _kr_filing_key(item: Mapping[str, Any]) -> Optional[str]:
    receipt = _receipt_number(item)
    if receipt is not None:
        return f"kr-filing:{receipt}"
    title = normalize_title(item.get("title"))
    day = _local_day(item, KST)
    if title and day:
        return f"kr-filing:{item.get('ticker')}|{day}|{title}"
    return None


def _uk_filing_key(item: Mapping[str, Any]) -> Optional[str]:
    metadata = item.get("raw_metadata") or {}
    rns_raw = metadata.get("rns_id") or (
        item.get("external_id")
        if str(item.get("source") or "") == "investegate"
        else None
    )
    rns_digits = re.sub(r"\D", "", str(rns_raw or ""))
    if rns_digits and len(rns_digits) >= 6:
        return f"uk:filing:rns:{rns_digits}"
    if str(item.get("source") or "") == "companies_house":
        transaction_id = str(item.get("external_id") or "").strip()
        if transaction_id:
            return f"uk:filing:ch:{transaction_id}"
    title = normalize_title(item.get("title"))
    day = _local_day(item, LONDON)
    if title and day:
        return (
            f"uk:filing:title:{item.get('source')}:"
            f"{item.get('ticker')}:{day}:{title}"
        )
    return None


def _hk_filing_key(item: Mapping[str, Any]) -> Optional[str]:
    source = str(item.get("source") or "")
    metadata = item.get("raw_metadata") or {}
    if source == "hkexnews":
        news_id = str(
            metadata.get("news_id") or item.get("external_id") or ""
        ).strip()
        if news_id:
            return f"hk:filing:news_id:{news_id}"
    if source == "hkex_di":
        serial = str(item.get("external_id") or "").strip()
        if serial:
            return f"hk:filing:di:{serial}"
    title = normalize_title(item.get("title"))
    day = _local_day(item, HKT)
    if title and day:
        return (
            f"hk:filing:title:{source}:"
            f"{item.get('ticker')}:{day}:{title}"
        )
    return None


def _tw_filing_key(item: Mapping[str, Any]) -> Optional[str]:
    """TW filings pair on a source-scoped title fallback only.

    ``twse_material`` and ``tpex_material`` share no cross-source receipt or
    NEWS_ID, and listing vs OTC boards should never be annotated against each
    other by title, so the source is part of the key. Same source, same
    ticker, same Taipei day and same normalized title share a key.
    """
    source = str(item.get("source") or "")
    title = normalize_title(item.get("title"))
    day = _local_day(item, TAIPEI)
    if title and day:
        return (
            f"tw:filing:title:{source}:"
            f"{item.get('ticker')}:{day}:{title}"
        )
    return None


def _news_key(item: Mapping[str, Any], market: str) -> Optional[str]:
    source = str(item.get("source") or "")
    if market == "us" and source not in _US_NEWS_SOURCES:
        return None
    if market == "jp" and source not in _JP_NEWS_SOURCES:
        return None
    if market == "kr" and source not in _KR_NEWS_SOURCES:
        return None
    zone = (
        KST
        if market == "kr"
        else HKT
        if market == "hk"
        else TAIPEI
        if market == "tw"
        else TORONTO
        if market == "ca"
        else SYDNEY
        if market == "au"
        else PARIS
        if market == "fr"
        else BERLIN
        if market == "de"
        else AMSTERDAM
        if market == "nl"
        else ROME
        if market == "it"
        else MADRID
        if market == "es"
        else SINGAPORE
        if market == "sg"
        else ZURICH
        if market == "ch"
        else WARSAW
        if market == "pl"
        else TALLINN
        if market in ("ee", "lv", "lt")
        else OSLO
        if market == "no"
        else LISBON
        if market == "pt"
        else VIENNA
        if market == "at"
        else KOLKATA
        if market == "in"
        else MEXICO_CITY
        if market == "mx"
        else JERUSALEM
        if market == "il"
        else BUDAPEST
        if market == "hu"
        else STOCKHOLM
        if market == "se"
        else BRUSSELS
        if market == "be"
        else LONDON
        if market == "aq"
        else LONDON
        if market == "cxe"
        else LUXEMBOURG
        if market == "emf"
        else LONDON
        if market == "trq"
        else BERLIN
        if market == "eux"
        else NEW_YORK
        if market == "us"
        else TOKYO
        if market == "jp"
        else LONDON
        if market == "uk"
        else LONDON
    )
    title = normalize_title(item.get("title"))
    day = _local_day(item, zone)
    if title and day:
        return f"{market}-news:{item.get('ticker')}|{day}|{title}"
    return None


def _community_key(item: Mapping[str, Any], market: str) -> Optional[str]:
    """Community soft-dedupe key (display-only; never drops rows).

    Prefer stable provider ids (HotCopper thread id, CEO.ca spiel id,
    Xueqiu status id); otherwise use a source-scoped title fallback so a
    future second community connector is never paired by title alone.
    """
    source = str(item.get("source") or "")
    metadata = item.get("raw_metadata") or {}
    if market == "au":
        thread_id = str(metadata.get("thread_id") or "").strip()
        if thread_id and source == "hotcopper_au":
            return f"au:community:hotcopper:{thread_id}"
        article_slug = str(metadata.get("article_slug") or "").strip()
        if article_slug and source == "stockhead_au":
            return f"au:community:stockhead:{article_slug}"
        title = normalize_title(item.get("title"))
        day = _local_day(item, SYDNEY)
        if title and day:
            return (
                f"au:community:title:{source}:"
                f"{item.get('ticker')}:{day}:{title}"
            )
        return None
    if market == "ca":
        spiel_id = str(metadata.get("spiel_id") or "").strip()
        if spiel_id and source == "ceoca_ca":
            return f"ca:community:ceoca:{spiel_id}"
        title = normalize_title(item.get("title"))
        day = _local_day(item, TORONTO)
        if title and day:
            return (
                f"ca:community:title:{source}:"
                f"{item.get('ticker')}:{day}:{title}"
            )
        return None
    if market == "uk":
        thread_id = str(metadata.get("thread_id") or "").strip()
        if thread_id and source == "lse_share_chat":
            return f"uk:community:lse_share_chat:{thread_id}"
        title = normalize_title(item.get("title"))
        day = _local_day(item, LONDON)
        if title and day:
            return (
                f"uk:community:title:{source}:"
                f"{item.get('ticker')}:{day}:{title}"
            )
        return None
    if market == "cn":
        status_id = str(metadata.get("status_id") or "").strip()
        if status_id and source == "xueqiu":
            return f"cn:community:xueqiu:{status_id}"
        title = normalize_title(item.get("title"))
        day = _local_day(item, SHANGHAI)
        if title and day:
            return (
                f"cn:community:title:{source}:"
                f"{item.get('ticker')}:{day}:{title}"
            )
        return None
    if market == "hk":
        status_id = str(metadata.get("status_id") or "").strip()
        if status_id and source == "xueqiu":
            return f"hk:community:xueqiu:{status_id}"
        title = normalize_title(item.get("title"))
        day = _local_day(item, HKT)
        if title and day:
            return (
                f"hk:community:title:{source}:"
                f"{item.get('ticker')}:{day}:{title}"
            )
        return None
    if market == "us":
        content_id = str(metadata.get("content_id") or "").strip()
        content_kind = str(metadata.get("content_kind") or "").strip()
        if content_id and source == "seeking_alpha":
            kind = content_kind or "item"
            return f"us:community:seeking_alpha:{kind}:{content_id}"
        title = normalize_title(item.get("title"))
        day = _local_day(item, NEW_YORK)
        if title and day:
            return (
                f"us:community:title:{source}:"
                f"{item.get('ticker')}:{day}:{title}"
            )
        return None
    return None


def _receipt_number(item: Mapping[str, Any]) -> Optional[str]:
    metadata = item.get("raw_metadata") or {}
    raw = (
        metadata.get("rcept_no")
        or metadata.get("acpt_no")
        or item.get("external_id")
    )
    digits = re.sub(r"\D", "", str(raw or ""))
    return digits if len(digits) == RECEIPT_LENGTH else None


def _local_day(
    item: Mapping[str, Any],
    zone: ZoneInfo,
) -> Optional[str]:
    raw = item.get("effective_at") or item.get("published_at")
    if not raw:
        return None
    try:
        parsed = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(zone).date().isoformat()


def _pick_primary(group: Sequence[Mapping[str, Any]]) -> Mapping[str, Any]:
    source_type = str(group[0].get("source_type") or "")
    if source_type == "regulatory_filing":
        priority = FILING_SOURCE_PRIORITY
    elif source_type == "community":
        priority = COMMUNITY_SOURCE_PRIORITY
    else:
        priority = NEWS_SOURCE_PRIORITY

    def rank(item: Mapping[str, Any]) -> Tuple[int, int]:
        return (
            priority.get(str(item.get("source")), 99),
            group.index(item),
        )

    return min(group, key=rank)
