# -*- coding: utf-8 -*-
"""Budapest Stock Exchange (BSE/BET) announcements connector (honest stub).

This is the Hungarian exchange (bse.hu / bet.hu). It has nothing to do
with the Indian BSE (bseindia.com), which is a separate locked boundary in
this repository. The final source decision follows the live recon results;
when no stable key-free issuer-announcement endpoint exists, collect()
stays empty and the connector marks itself stub.
"""
from typing import List, Tuple

from ..models import CollectionRequest, InformationItem


class BseHuAnnouncementsConnector:
    """Budapest Stock Exchange issuer announcements (honest stub)."""

    name = "bse_hu_announcements"
    provider = "Budapest Stock Exchange"

    def __init__(self) -> None:
        self._last_errors: Tuple[Tuple[str, str], ...] = ()
        self.last_collection_status = "stub"

    @property
    def last_errors(self) -> Tuple[Tuple[str, str], ...]:
        return self._last_errors

    def collect(self, request: CollectionRequest) -> List[InformationItem]:
        return []


__all__ = ["BseHuAnnouncementsConnector"]
