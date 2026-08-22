# -*- coding: utf-8 -*-
"""Wiener Börse official issuer/ad-hoc news."""

from __future__ import annotations

import re
from datetime import date, datetime
from typing import Any, Iterable, Mapping, Optional, Sequence
from urllib.parse import urljoin
from zoneinfo import ZoneInfo

from ..models import MARKET_AT
from ..universe.at_universe import at_universe_name_map
from ..web_repository import normalize_at_ticker
from ._public_disclosure import PublicDisclosureConnector, clean_html, paged_urls, stable_id

BASE_URL = "https://www.wienerborse.at"
NEWS_URL = BASE_URL + "/en/news-1/"


def _parse_page(text: str, retrieval_url: str) -> Sequence[Mapping[str, Any]]:
    records = []
    for block in text.split('<div class="news-row">')[1:]:
        block = block.split('<div class="news-row">', 1)[0]
        kind_date = re.search(
            r'(Ad-hoc News|Corporate News)\s*[·&middot;]+\s*([0-9/.,:\s]+)',
            clean_html(block), flags=re.I,
        )
        link = re.search(
            r'<div[^>]*class=["\'][^"\']*header-shorten[^"\']*["\'][^>]*>.*?<a[^>]*href=["\']([^"\']+)["\'][^>]*>(.*?)</a>',
            block, flags=re.I | re.S,
        )
        if not (kind_date and link):
            continue
        raw_date = kind_date.group(2).strip(" .,")
        published = None
        for fmt in ("%m/%d/%Y, %H:%M:%S", "%m/%d/%Y %H:%M:%S", "%d.%m.%Y, %H:%M:%S"):
            try:
                published = datetime.strptime(raw_date, fmt).replace(tzinfo=ZoneInfo("Europe/Vienna"))
                break
            except ValueError:
                pass
        if published is None:
            continue
        url = urljoin(BASE_URL, link.group(1))
        native = re.search(r'(?:c93603%5Bfile%5D|c93603\[file\])=(\d+)', url)
        records.append({
            "external_id": f"wiener-boerse:{native.group(1)}" if native else stable_id("wiener-boerse", url),
            "issuer": clean_html(link.group(2)).split(":", 1)[0],
            "published_at": published,
            "published_at_raw": raw_date,
            "published_timezone": "Europe/Vienna",
            "title": clean_html(link.group(2)),
            "document_type": kind_date.group(1),
            "url": url,
            "retrieval_url": retrieval_url,
            "raw_payload": block,
            "raw_payload_format": "html",
        })
    return records


class WienerBoerseClient:
    timezone = ZoneInfo("Europe/Vienna")

    def fetch(self, start_date: date, end_date: date) -> Iterable[Mapping[str, Any]]:
        return paged_urls(
            lambda page: f"{NEWS_URL}?c93603-page={page}&per-page=100",
            _parse_page,
            start_date,
            max_pages=50,
        )


class WienerBoerseNewsConnector(PublicDisclosureConnector):
    name = "wiener_boerse_news"
    provider = "Wiener Börse"
    coverage_level = "official_exchange_news"

    def __init__(self, client: Optional[Any] = None, universe: Optional[Mapping[str, Mapping[str, str]]] = None) -> None:
        super().__init__(client=client or WienerBoerseClient(), universe=universe if universe is not None else at_universe_name_map(), normalizer=normalize_at_ticker, market=MARKET_AT)


__all__ = ["WienerBoerseClient", "WienerBoerseNewsConnector"]
