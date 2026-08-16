# -*- coding: utf-8 -*-
"""BMV Eventos Relevantes connector (honest stub).

Recon (2026-08-15): bmv.com.mx is a legacy Liferay-style site; the
eventos-relevantes/listed-companies deep paths return HTTP 404 and no
stable key-free JSON endpoint was found under /api/*. collect() stays
empty and the connector marks itself stub instead of scraping an
undocumented surface. BIVA is a React SPA with no server-rendered events.
"""
from typing import List, Tuple

from ..models import CollectionRequest, InformationItem


class BmvRelevantEventsConnector:
    """BMV Eventos Relevantes (honest stub)."""

    name = "bmv_relevant_events"
    provider = "BMV"

    def __init__(self) -> None:
        self._last_errors: Tuple[Tuple[str, str], ...] = ()
        self.last_collection_status = "stub"

    @property
    def last_errors(self) -> Tuple[Tuple[str, str], ...]:
        return self._last_errors

    def collect(self, request: CollectionRequest) -> List[InformationItem]:
        return []


__all__ = ["BmvRelevantEventsConnector"]
