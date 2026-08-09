"""Shared Yahoo Finance RSS parsing helpers (UK and HK news connectors).

Both connectors use the same feed parsing so behaviour cannot drift. The
parser raises ``data_error`` (a per-connector exception class) instead of
faking success on malformed feeds.
"""

from __future__ import annotations

import hashlib
import html
import os
import re
from datetime import date, datetime
from email.utils import parsedate_to_datetime
from typing import Any, List, Mapping, Optional
import xml.etree.ElementTree as ElementTree


class RssDataError(Exception):
    """Default data error for shared RSS parsing."""


def _parse_rss(
    body: bytes,
    *,
    start_date: date,
    end_date: date,
    data_error: type = RssDataError,
) -> List[Mapping[str, Any]]:
    try:
        root = ElementTree.fromstring(body)
    except ElementTree.ParseError as error:
        raise data_error("Yahoo news response is not valid XML.") from error
    if str(root.tag).split("}")[-1].lower() != "rss":
        raise data_error("Yahoo news response is not an RSS feed.")
    records: List[Mapping[str, Any]] = []
    for item in root.iter():
        if str(item.tag).split("}")[-1].lower() != "item":
            continue
        title = _child_text(item, "title")
        link = _child_text(item, "link")
        if not title or not link:
            continue
        published = _parse_rfc822(_child_text(item, "pubDate"))
        if published is None:
            continue
        if not start_date <= published.date() <= end_date:
            continue
        description = _child_text(item, "description")
        records.append(
            {
                "external_id": _article_id(link),
                "title": html.unescape(title).strip(),
                "url": link,
                "published": published,
                "summary": _clean_description(description),
            }
        )
    return records


def _child_text(element: Any, local_name: str) -> str:
    for child in element:
        if str(child.tag).split("}")[-1].lower() == local_name.lower():
            return child.text or ""
    return ""


def _parse_rfc822(value: str) -> Optional[datetime]:
    try:
        parsed = parsedate_to_datetime(value.strip())
    except (TypeError, ValueError):
        return None
    return parsed


def _article_id(url: str) -> str:
    match = re.search(r"[-/](\d{6,})\.html", url)
    if match is not None:
        return match.group(1)
    return hashlib.sha1(url.encode("utf-8")).hexdigest()


def _clean_description(value: str) -> Optional[str]:
    if not value:
        return None
    text = html.unescape(re.sub(r"<[^>]+>", " ", value))
    text = re.sub(r"\s+", " ", text).strip()
    return text or None


def _quote(symbol: str) -> str:
    from urllib.parse import quote

    return quote(symbol)


def _read_float_environment(name: str, default: float) -> float:
    value = os.environ.get(name)
    if value is None:
        return default
    try:
        return float(value)
    except ValueError as error:
        raise ValueError(f"{name} must be a number.") from error


def _read_int_environment(name: str, default: int) -> int:
    value = os.environ.get(name)
    if value is None:
        return default
    try:
        return int(value)
    except ValueError as error:
        raise ValueError(f"{name} must be an integer.") from error
