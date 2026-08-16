# -*- coding: utf-8 -*-
"""MAYA / TASE announcements connector (honest stub).

The final source decision follows the live recon results. When no stable
key-free MAYA/TASE endpoint exists, collect() stays empty and the
connector marks itself stub; a future real endpoint can be wired without
changing the connector contract.
"""
from typing import List, Tuple

from ..models import CollectionRequest, InformationItem


class MayaAnnouncementsConnector:
    """MAYA / TASE company announcements (honest stub)."""

    name = "maya_announcements"
    provider = "MAYA (TASE)"

    def __init__(self) -> None:
        self._last_errors: Tuple[Tuple[str, str], ...] = ()
        self.last_collection_status = "stub"

    @property
    def last_errors(self) -> Tuple[Tuple[str, str], ...]:
        return self._last_errors

    def collect(self, request: CollectionRequest) -> List[InformationItem]:
        return []


__all__ = ["MayaAnnouncementsConnector"]
