# -*- coding: utf-8 -*-
"""AT-1 披露 stub 连接器（官方/EQS 均无稳定免 key 通道）。"""
from typing import List, Tuple

from ..models import CollectionRequest, InformationItem


class WienerBoerseNewsConnector:
    """Wiener Börse issuer news (honest stub).

    Recon (2026-08-15): no stable key-free disclosure endpoint found on
    wienerborse.at (TYPO3/client-side rendered pages) and EQS Austria
    returns empty records for sampled AT ISINs, so this connector keeps
    collect() empty and is marked stub instead of faking coverage.
    """

    name = "wiener_boerse_news"
    provider = "Wiener Börse"

    def __init__(self) -> None:
        self._last_errors: Tuple[Tuple[str, str], ...] = ()
        self.last_collection_status = "stub"

    @property
    def last_errors(self) -> Tuple[Tuple[str, str], ...]:
        return self._last_errors

    def collect(self, request: CollectionRequest) -> List[InformationItem]:
        return []


__all__ = ["WienerBoerseNewsConnector"]
