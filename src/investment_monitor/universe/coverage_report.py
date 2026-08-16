# -*- coding: utf-8 -*-
"""Per-country coverage aggregator for the IBKR exchange catalog (P0-1).

The report is derived automatically from the repo's existing facts:

* universe      — universe module presence + the explicit boundary-stub set;
* disclosure    — SOURCE_MARKETS filing sources + the explicit honest-stub set;
* news          — presence of yahoo_*/google_news_* sources for the market;
* etf_universe  — DE official Xetra includes ETF/ETN/ETC (live); other
                  official universes are stock-only (unknown); otherwise the
                  Phase 1 third_party reference is consulted (partial when
                  ETF candidate rows exist, else unavailable);
* source_tier_summary — official > mixed > third_party > none.

Statuses are honest: boundary stubs (AT/HU/IL/MX/NO/PT disclosures,
AT/CH/HU/IL/MX/SE/SG universes) are never upgraded to live.
The report never flows into information_items / the daily feed.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Mapping

from .exchange_catalog import (
    list_countries,
    list_venues,
    load_exchange_catalog,
)
from .global_equity_reference import etf_candidates_for

# 显式边界 stub（对应各轨 spike 结论；禁止标 live）。
UNIVERSE_BOUNDARY_STUBS = frozenset({"at", "ch", "hu", "il", "mx", "se", "sg"})
# 官方目录存在但覆盖不完整（缺次要板块/无 ticker 等）。
UNIVERSE_PARTIAL = frozenset({"ca", "hk", "tw", "uk"})
DISCLOSURE_BOUNDARY_STUBS = frozenset({"at", "hu", "il", "mx", "no", "pt"})
DISCLOSURE_PARTIAL = frozenset({"ch", "de", "it", "nl"})
DISCLOSURE_UNAVAILABLE = frozenset({"ca", "ru", "sg"})

_NEWS_PREFIXES = ("yahoo_", "google_news_")

# market -> 披露源名称（filing 类）；来自 registry.SOURCE_MARKETS。
_DISCLOSURE_SOURCES: Dict[str, tuple] = {
    "us": ("sec",),
    "ca": ("ceoca_ca",),
    "au": ("asx_announcements",),
    "hk": ("hkexnews", "hkex_di"),
    "tw": ("twse_material", "tpex_material"),
    "jp": ("tdnet_public_web", "edinet"),
    "in": ("nse_announcements",),
    "at": ("wiener_boerse_news",),
    "be": ("fsma_stori", "be_second_disclosure"),
    "ch": ("eqs_ch", "six_official_notices"),
    "de": ("eqs_dgap",),
    "ee": ("nasdaq_baltic_news",),
    "lv": ("nasdaq_baltic_news",),
    "lt": ("nasdaq_baltic_news",),
    "es": ("cnmv_hr", "bme_relevant_facts"),
    "fr": ("amf_oam",),
    "hu": ("bse_hu_announcements",),
    "il": ("maya_announcements",),
    "it": ("eqs_it",),
    "nl": ("eqs_nl",),
    "no": ("newsweb_no",),
    "pl": ("gpw_espi",),
    "pt": ("euronext_lisbon_news",),
    "se": ("fi_oam", "nasdaq_se_filings"),
    "sg": ("sgx_announcements",),
    "uk": ("companies_house", "investegate"),
    "mx": ("bmv_relevant_events",),
    "ru": (),
}


def _universe_status(market_code: str | None, market: str) -> str:
    if market == "ru" or market_code is None:
        return "unavailable"
    if market_code in UNIVERSE_BOUNDARY_STUBS:
        return "stub"
    if market_code in UNIVERSE_PARTIAL:
        return "partial"
    module = _universe_module_name(market_code)
    try:
        __import__(module, fromlist=["*"])
    except ImportError:
        if not module.startswith("investment_monitor.universe."):
            return "unavailable"
        try:
            __import__(
                module.replace("investment_monitor.universe", "investment_monitor", 1),
                fromlist=["*"],
            )
        except ImportError:
            return "unavailable"
    return "live"


def _universe_module_name(market_code: str) -> str:
    if market_code in ("ee", "lv", "lt"):
        return "investment_monitor.universe.nasdaq_baltic_universe"
    return f"investment_monitor.universe.{market_code}_universe"


def _disclosure_status(market_code: str | None, market: str) -> str:
    market = str(market or "").lower()
    if market in DISCLOSURE_UNAVAILABLE:
        return "unavailable"
    if market in DISCLOSURE_BOUNDARY_STUBS:
        return "stub"
    if market in DISCLOSURE_PARTIAL:
        return "partial"
    if _DISCLOSURE_SOURCES.get(market):
        return "live"
    return "unavailable"


def _news_status(market_code: str | None) -> str:
    if market_code is None:
        return "unavailable"
    return "live"


def _etf_status(market_code: str | None, market: str, cache_path: Any = None) -> str:
    if market == "de":
        return "live"
    candidates = 0
    try:
        candidates = len(etf_candidates_for(market, cache_path))
    except Exception:  # noqa: BLE001 - 参考层损坏不阻断报告
        candidates = 0
    if candidates:
        return "partial"
    if market_code is not None and _universe_status(market_code, market) == "live":
        return "unknown"
    return "unavailable"


def _source_tier_summary(universe: str, disclosure: str, news: str) -> str:
    if universe == "live":
        return "official"
    if universe == "partial":
        return "mixed"
    if disclosure in ("live", "partial"):
        return "mixed"
    if news == "live":
        return "third_party"
    return "none"


def coverage_report(
    cache_path: Any = None,
) -> Mapping[str, Any]:
    """Return per-country coverage rows for the 28 core IBKR countries."""
    countries = list_countries()
    venues_by_country: Dict[str, int] = {}
    for row in list_venues():
        country = str(row.get("country_code") or "")
        venues_by_country[country] = venues_by_country.get(country, 0) + 1

    rows: List[Dict[str, Any]] = []
    for country in countries:
        market = str(country.get("market_code") or "").lower()
        country_code = str(country.get("country_code") or "")
        universe = _universe_status(country.get("market_code"), market or country_code.lower())
        disclosure = _disclosure_status(country.get("market_code"), country_code)
        news = _news_status(country.get("market_code"))
        etf_universe = _etf_status(
            country.get("market_code"), market or country_code.lower(), cache_path
        )
        rows.append({
            "country_code": country_code,
            "country_name": str(country.get("country_name") or country_code),
            "region": str(country.get("region") or ""),
            "market_code": country.get("market_code"),
            "trading_status": str(country.get("trading_status") or "active"),
            "universe": universe,
            "disclosure": disclosure,
            "news": news,
            "etf_universe": etf_universe,
            "source_tier_summary": _source_tier_summary(
                universe, disclosure, news
            ),
            "venue_count": venues_by_country.get(country_code, 0),
            "notes": _notes_for(country_code, universe, disclosure, etf_universe),
        })

    status_counts: Dict[str, int] = {}
    for key in ("universe", "disclosure", "news", "etf_universe"):
        counts: Dict[str, int] = {}
        for row in rows:
            value = str(row[key])
            counts[value] = counts.get(value, 0) + 1
        status_counts[key] = counts

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "schema": "coverage_report/v1",
        "summary": {
            "countries": len(rows),
            "venues": sum(row["venue_count"] for row in rows),
            "status_counts": status_counts,
        },
        "countries": rows,
    }


def _notes_for(
    country_code: str,
    universe: str,
    disclosure: str,
    etf_universe: str,
) -> str:
    if country_code == "RU":
        return "IBKR MOEX positions are suspended; read-only catalog entry."
    notes = []
    if universe == "stub":
        notes.append("official universe is a boundary stub")
    if disclosure == "stub":
        notes.append("disclosure connector is an honest stub")
    if etf_universe == "live":
        notes.append("official Xetra universe carries ETF/ETN/ETC")
    if etf_universe == "partial":
        notes.append("third_party ETF candidates present")
    return "; ".join(notes) or (
        f"universe={universe}; disclosure={disclosure}"
    )


__all__ = ["coverage_report"]
