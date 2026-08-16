# -*- coding: utf-8 -*-
"""Honest stub connectors for NO/PT disclosure primary chains.

ENP-1 live recon (2026-08-15):
- Norway NewsWeb (https://newsweb.oslobors.no/) is the statutory OAM but
  its message list is a JavaScript SPA served through an obfuscated
  bundle; no stable key-free JSON endpoint is exposed under /api/* (every
  path returns the same SPA shell). collect() stays empty instead of
  scraping an undocumented surface.
- Euronext Lisbon company pages
  (https://live.euronext.com/en/product/equities/PTEDP0AM0009-XLIS)
  render announcements through client-side components; the probed ajax
  press-release endpoints return 404. No stable key-free JSON was found.
Both connectors therefore return [] and mark themselves "stub" honestly;
universe/news slices continue with the ENP-2/ENP-3 sources.
"""

from __future__ import annotations

from typing import List, Tuple

from ..models import CollectionRequest, InformationItem, MARKET_NO, MARKET_PT

_MARKETS = (MARKET_NO, MARKET_PT)


class NewswebNoConnector:
    """Norwegian NewsWeb statutory OAM (honest stub pending a stable API)."""

    name = "newsweb_no"
    provider = "NewsWeb (Oslo Børs)"

    def __init__(self) -> None:
        self._last_errors: Tuple[Tuple[str, str], ...] = ()
        self.last_collection_status = "stub"

    @property
    def last_errors(self) -> Tuple[Tuple[str, str], ...]:
        return self._last_errors

    def collect(self, request: CollectionRequest) -> List[InformationItem]:
        return []


class EuronextLisbonNewsConnector:
    """Euronext Lisbon company news (honest stub pending a stable API)."""

    name = "euronext_lisbon_news"
    provider = "Euronext Lisbon"

    def __init__(self) -> None:
        self._last_errors: Tuple[Tuple[str, str], ...] = ()
        self.last_collection_status = "stub"

    @property
    def last_errors(self) -> Tuple[Tuple[str, str], ...]:
        return self._last_errors

    def collect(self, request: CollectionRequest) -> List[InformationItem]:
        return []


__all__ = ["EuronextLisbonNewsConnector", "NewswebNoConnector"]
