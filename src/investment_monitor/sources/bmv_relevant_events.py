# -*- coding: utf-8 -*-
"""Partial, public BMV issuer-event bulletin connector.

BMV's Sala de Prensa is a rolling HTML bulletin, not its complete periodic
financial-information archive (that product is sold separately).  Treat the
feed as a partial issuer-event source and fail closed if its pagination or
markup stops being trustworthy.
"""

from __future__ import annotations

import re
import time
from datetime import date, datetime
from typing import Any, Callable, Iterable, Mapping, Optional, Sequence, Tuple
from urllib.parse import urljoin
from zoneinfo import ZoneInfo

from ..models import MARKET_MX
from ..universe.mx_universe import mx_universe_name_map
from ..web_repository import normalize_mx_ticker
from ._public_disclosure import (
    PublicDisclosureConnector,
    PublicDisclosureError,
    clean_html,
    fetch_text,
    stable_id,
)

BASE_URL = "https://www.bmv.com.mx"
FIRST_PAGE = BASE_URL + "/es/sala-de-prensa?viewPage=EVENTOS_RELEVANTES"
# BMV's page-one link is different; subsequent page indexes are one-based.
PAGE_URL = (
    BASE_URL
    + "/es/Grupo_BMV/Sala_de_Prensa/_rid/240/_mod/CHANGE_PAGE?index={}&viewPage=EVENTOS_RELEVANTES"
)

_NATIVE_ID = re.compile(r"_(\d+)_\d+\.[A-Za-z0-9]+(?:[?#].*)?$")
_MARKET_NOTICE = re.compile(
    r"\b(?:INICIA|REINICIA|SUSPEN[SDIÓ]|LEVANTAMIENTO|SUBASTA|"
    r"AVISO\s+DE\s+MERCADO|MOVIMIENTOS?\s+INUSITADOS?)\b",
    re.I,
)
_RATING_EVENT = re.compile(
    r"\b(?:CALIFICACI[ÓO]N|RATINGS?|MOODY'?S|FITCH|HR\s+RATINGS|"
    r"PCR\s+VERUM)\b",
    re.I,
)


def _row_category(title: str, issuer: str, attachments: Sequence[str]) -> str:
    """Classify only events safe to present as issuer regulatory filings."""
    attachment_text = " ".join(attachments).casefold()
    if "inisubmv" in attachment_text or _MARKET_NOTICE.search(title):
        return "market_notice"
    if _RATING_EVENT.search(title):
        return "third_party_rating"
    # A normal BMV event row identifies an issuer key but does not expose a
    # security series or ISIN.  Leave any future non-standard rows pending,
    # rather than silently treating them as an issuer filing.
    return "issuer_event" if issuer else "pending_matching"


def _attachment_links(row: str) -> Sequence[Tuple[str, str]]:
    links = []
    seen = set()
    for match in re.finditer(
        r'<a\b[^>]*href=["\']([^"\']*?/docs-pub/[^"\']+)["\'][^>]*>(.*?)</a>',
        row,
        flags=re.I | re.S,
    ):
        url = urljoin(BASE_URL, match.group(1))
        if url in seen:
            continue
        seen.add(url)
        links.append((url, clean_html(match.group(2)).upper()))
    return links


def _parse_page(text: str, retrieval_url: str) -> Sequence[Mapping[str, Any]]:
    """Parse every structurally complete bulletin row, retaining its category.

    The client filters non-issuer categories.  Keeping the classification in
    the raw record makes ambiguous future rows auditable instead of allowing
    them to be silently relabelled as filings.
    """
    records = []
    for row in re.findall(r"<tr\b[^>]*>(.*?)</tr>", text, flags=re.I | re.S):
        title_match = re.search(r"<h2[^>]*>(.*?)</h2>", row, flags=re.I | re.S)
        if not title_match:
            continue
        strongs = re.findall(r"<strong[^>]*>(.*?)</strong>", row, flags=re.I | re.S)
        links = _attachment_links(row)
        if len(strongs) < 2 or not links:
            raise PublicDisclosureError(
                "BMV event row markup changed (expected timestamp, issuer, and attachment)"
            )
        raw_date = clean_html(strongs[0])
        try:
            published = datetime.strptime(raw_date.upper(), "%Y-%m-%d %I:%M %p").replace(
                tzinfo=ZoneInfo("America/Mexico_City")
            )
        except ValueError as error:
            raise PublicDisclosureError(
                f"BMV event row has an unparseable timestamp: {raw_date!r}"
            ) from error
        issuer = clean_html(strongs[1]).upper()
        title = clean_html(title_match.group(1))
        attachments = [url for url, _label in links]
        primary = next(
            (url for url, label in links if "PRINCIPAL" in label), attachments[0]
        )
        native = _NATIVE_ID.search(primary) or _NATIVE_ID.search(attachments[0])
        category = _row_category(title, issuer, attachments)
        if category == "issuer_event" and not native:
            raise PublicDisclosureError(
                "BMV issuer event has no native document identifier"
            )
        external_id = (
            f"bmv-event:{native.group(1)}"
            if native else stable_id("bmv-nonissuer", primary)
        )
        records.append({
            "external_id": external_id,
            "native_id": native.group(1) if native else None,
            "ticker": issuer,
            "issuer": issuer,
            "published_at": published,
            "published_at_raw": raw_date,
            "published_timezone": "America/Mexico_City",
            "title": title,
            "document_type": "evento relevante" if category == "issuer_event" else category,
            "classification_code": category,
            "url": primary,
            "detail_url": primary,
            "attachments": attachments,
            "retrieval_url": retrieval_url,
            "raw_payload": row,
            "raw_payload_format": "html",
        })
    return records


def _has_bulletin_structure(text: str) -> bool:
    # This text is present in the public bulletin's page body and lets a valid
    # zero-announcement page remain an honest empty result.  A login/WAF/error
    # page must never be mistaken for one.
    return "EVENTOS RELEVANTES" in clean_html(text).upper()


class BmvRelevantEventsClient:
    timezone = ZoneInfo("America/Mexico_City")

    def __init__(
        self,
        *,
        fetcher: Callable[[str], Tuple[str, Mapping[str, str]]] = fetch_text,
        sleeper: Callable[[float], None] = time.sleep,
        max_pages: int = 500,
        max_attempts: int = 3,
        retry_delay: float = 0.5,
        page_delay: float = 0.15,
    ) -> None:
        if max_pages < 1 or max_attempts < 1:
            raise ValueError("max_pages and max_attempts must be positive")
        self._fetcher = fetcher
        self._sleeper = sleeper
        self._max_pages = max_pages
        self._max_attempts = max_attempts
        self._retry_delay = retry_delay
        self._page_delay = page_delay
        self.pending_records: Tuple[Mapping[str, Any], ...] = ()

    def _read_page(self, url: str) -> str:
        last_error: Optional[Exception] = None
        for attempt in range(self._max_attempts):
            try:
                text, _headers = self._fetcher(url)
                return text
            except Exception as error:  # transport failures are retriable, parsing is not
                last_error = error
                if attempt + 1 < self._max_attempts:
                    self._sleeper(self._retry_delay * (2**attempt))
        raise PublicDisclosureError(
            f"BMV bulletin request failed after {self._max_attempts} attempts: {url}: {last_error}"
        ) from last_error

    def fetch(self, start_date: date, end_date: date) -> Iterable[Mapping[str, Any]]:
        if end_date < start_date:
            raise ValueError("end_date must not precede start_date")
        seen_ids: set[str] = set()
        prior_oldest: Optional[datetime] = None
        pending: list[Mapping[str, Any]] = []
        self.pending_records = ()
        for page in range(1, self._max_pages + 1):
            if page > 1 and self._page_delay:
                self._sleeper(self._page_delay)
            url = FIRST_PAGE if page == 1 else PAGE_URL.format(page)
            text = self._read_page(url)
            if not _has_bulletin_structure(text):
                raise PublicDisclosureError(f"BMV bulletin structure missing on page {page}")
            records = list(_parse_page(text, url))
            if not records:
                # A valid bulletin page with no event rows is the only empty
                # terminal condition.  Any malformed event row already raised.
                self.pending_records = tuple(pending)
                return
            page_ids = {str(record["external_id"]) for record in records}
            if page_ids & seen_ids:
                raise PublicDisclosureError(
                    f"BMV pagination repeated or overlapped records on page {page}"
                )
            timestamps = [record["published_at"] for record in records]
            if any(timestamps[index] < timestamps[index + 1] for index in range(len(timestamps) - 1)):
                raise PublicDisclosureError(f"BMV page {page} is not in descending publication order")
            oldest = min(timestamps)
            newest = max(timestamps)
            if prior_oldest is not None and newest > prior_oldest:
                raise PublicDisclosureError(f"BMV pagination order regressed on page {page}")
            prior_oldest = oldest
            seen_ids.update(page_ids)
            for record in records:
                category = str(record.get("classification_code") or "")
                if category in {"market_notice", "third_party_rating"}:
                    continue
                if category == "pending_matching":
                    pending.append(record)
                published = record["published_at"]
                if start_date <= published.date() <= end_date:
                    yield record
            if oldest.date() < start_date:
                self.pending_records = tuple(pending)
                return
        self.pending_records = tuple(pending)
        raise PublicDisclosureError(
            f"BMV pagination reached hard cap ({self._max_pages}) before page older than {start_date}"
        )


class BmvRelevantEventsConnector(PublicDisclosureConnector):
    name = "bmv_relevant_events"
    provider = "Bolsa Mexicana de Valores"
    coverage_level = "official"
    source_wide_collection = True
    preserve_unmatched_records = True

    def __init__(self, client: Optional[Any] = None, universe: Optional[Mapping[str, Mapping[str, str]]] = None) -> None:
        super().__init__(client=client or BmvRelevantEventsClient(), universe=universe if universe is not None else mx_universe_name_map(), normalizer=normalize_mx_ticker, market=MARKET_MX)


__all__ = ["BmvRelevantEventsClient", "BmvRelevantEventsConnector"]
