"""Strict, allowlisted Canadian issuer IR filing-feed connector.

The source is intentionally conservative: an issuer must explicitly configure
each feed and its permitted URL prefixes.  A parser failure invalidates that
whole source response, so a changed page cannot be silently treated as an
empty filing window.  This connector is Tier 2 issuer provenance only, never
an official SEDAR+ archive or a general-purpose news scraper.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timezone
from email.utils import parsedate_to_datetime
from html.parser import HTMLParser
import json
import os
from pathlib import Path
import socket
import time as time_module
from typing import Any, Callable, Iterable, List, Mapping, Optional, Sequence, Tuple
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin, urlparse
from urllib.request import Request, urlopen
from xml.etree import ElementTree
from zoneinfo import ZoneInfo

from ...models import CollectionRequest, InformationItem, MARKET_CA
from ...connectors.base import ConnectorUnavailableError
from ...provenance import build_raw_provenance
from ...web_repository import normalize_ca_ticker


_FORMATS = frozenset({"rss", "atom", "json", "sitemap", "html"})
_EXCHANGES = frozenset({"TSX", "TSXV", "CSE", "NEO"})
_USER_AGENT = "InvestmentMonitor/ca-ir (configured issuer filing feeds)"
CONFIG_SCHEMA = "ca_ir_sources/v1"


class CaIrError(ValueError):
    """Base error for a configured Canadian issuer-IR source."""


class CaIrRequestError(CaIrError):
    """The configured issuer source was unavailable (including 403/429)."""


class CaIrDataError(CaIrError):
    """A response is unsafe or no longer matches its strict feed contract."""


@dataclass(frozen=True)
class CaIrUrlRule:
    """One exact host plus path-prefix allowlist rule for an issuer feed."""

    host: str
    path_prefix: str = "/"

    def __post_init__(self) -> None:
        host = str(self.host).strip().lower().rstrip(".")
        prefix = str(self.path_prefix).strip() or "/"
        if not host or ":" in host or "/" in host:
            raise ValueError("CaIrUrlRule.host must be a bare hostname")
        if not prefix.startswith("/"):
            raise ValueError("CaIrUrlRule.path_prefix must start with '/'")
        object.__setattr__(self, "host", host)
        object.__setattr__(self, "path_prefix", prefix.rstrip("/") or "/")

    def permits(self, value: str) -> bool:
        parsed = urlparse(value)
        path = parsed.path or "/"
        return (
            parsed.scheme == "https"
            and not parsed.username
            and not parsed.password
            and parsed.port in (None, 443)
            and (parsed.hostname or "").lower().rstrip(".") == self.host
            and (self.path_prefix == "/" or path == self.path_prefix
                 or path.startswith(self.path_prefix + "/"))
        )


@dataclass(frozen=True)
class CaIrSource:
    """Reviewed configuration for exactly one issuer-owned filing feed.

    ``filing_terms`` is mandatory.  A press release that does not contain one
    of those reviewed terms in its title or URL is deliberately excluded.
    ``publisher_kind`` makes a media/newswire configuration invalid even if a
    caller supplies a URL allowlist for it.
    """

    source_id: str
    ticker: str
    issuer: str
    exchange: str
    feed_url: str
    format: str
    url_rules: Tuple[CaIrUrlRule, ...]
    filing_terms: Tuple[str, ...]
    page_urls: Tuple[str, ...] = ()
    timezone: str = "America/Toronto"
    publisher_kind: str = "issuer_ir"

    def __post_init__(self) -> None:
        source_id = str(self.source_id).strip()
        ticker = normalize_ca_ticker(self.ticker)
        issuer = str(self.issuer).strip()
        exchange = str(self.exchange).strip().upper()
        feed_url = str(self.feed_url).strip()
        fmt = str(self.format).strip().lower()
        rules = tuple(self.url_rules)
        terms = tuple(
            term.strip().casefold() for term in self.filing_terms if str(term).strip()
        )
        publisher_kind = str(self.publisher_kind).strip().lower()
        page_urls = tuple(str(url).strip() for url in self.page_urls if str(url).strip())
        if not source_id or not ticker or not issuer:
            raise ValueError("CaIrSource source_id, ticker, and issuer are required")
        if exchange not in _EXCHANGES:
            raise ValueError("CaIrSource.exchange must be one of TSX, TSXV, CSE, NEO")
        if fmt not in _FORMATS:
            raise ValueError("CaIrSource.format must be rss, atom, json, sitemap, or html")
        if publisher_kind != "issuer_ir":
            raise ValueError("CaIrSource only permits issuer_ir publisher_kind")
        if not rules or not all(isinstance(rule, CaIrUrlRule) for rule in rules):
            raise ValueError("CaIrSource.url_rules must contain CaIrUrlRule entries")
        if not terms:
            raise ValueError("CaIrSource.filing_terms must be explicitly configured")
        if not any(rule.permits(feed_url) for rule in rules):
            raise ValueError("CaIrSource.feed_url must match an allowlisted https host/path")
        if len(page_urls) > 99 or any(
            not any(rule.permits(url) for rule in rules) for url in page_urls
        ):
            raise ValueError("CaIrSource.page_urls exceed the cap or allowlist")
        try:
            ZoneInfo(str(self.timezone))
        except Exception as error:
            raise ValueError("CaIrSource.timezone must be an IANA timezone") from error
        object.__setattr__(self, "source_id", source_id)
        object.__setattr__(self, "ticker", ticker)
        object.__setattr__(self, "issuer", issuer)
        object.__setattr__(self, "exchange", exchange)
        object.__setattr__(self, "feed_url", feed_url)
        object.__setattr__(self, "format", fmt)
        object.__setattr__(self, "url_rules", rules)
        object.__setattr__(self, "filing_terms", terms)
        object.__setattr__(self, "page_urls", page_urls)
        object.__setattr__(self, "publisher_kind", publisher_kind)

    def permits_url(self, value: str, *, base_url: Optional[str] = None) -> str:
        resolved = urljoin(base_url or self.feed_url, str(value).strip())
        if not any(rule.permits(resolved) for rule in self.url_rules):
            raise CaIrDataError("record URL is outside configured issuer allowlist")
        return resolved


@dataclass(frozen=True)
class CaIrResponse:
    """Injectable HTTP response for deterministic, offline connector tests."""

    text: str
    headers: Mapping[str, str] = None  # type: ignore[assignment]

    def __post_init__(self) -> None:
        object.__setattr__(self, "text", str(self.text))
        object.__setattr__(self, "headers", dict(self.headers or {}))


@dataclass(frozen=True)
class _Record:
    external_id: str
    title: str
    published: datetime
    published_raw: str
    url: str
    attachments: Tuple[str, ...]
    summary: Optional[str]
    raw: Mapping[str, Any]


class CaIrConnector:
    """Collect reviewed Canadian issuer IR filing feeds without discovery."""

    name = "ca_ir"
    provider = "Issuer-configured Canadian investor-relations feeds (Tier 2)"
    coverage_level = "tier_2_issuer_ir_partial"
    coverage_kind = "feed_snapshot"
    source_type = "regulatory_filing"
    max_lookback_days = 31

    def __init__(
        self,
        *,
        sources: Iterable[CaIrSource] = (),
        fetcher: Optional[Callable[[str], Any]] = None,
        retry_attempts: int = 3,
        rate_limit_seconds: Optional[float] = None,
        sleeper: Callable[[float], None] = time_module.sleep,
    ) -> None:
        configured = tuple(sources)
        identifiers = [source.source_id for source in configured]
        if len(set(identifiers)) != len(identifiers):
            raise ValueError("CaIrSource.source_id values must be unique")
        self._sources = configured
        self._fetcher = fetcher or _fetch_text
        self._retry_attempts = max(1, int(retry_attempts))
        self._rate_limit_seconds = (
            (0.25 if fetcher is None else 0.0)
            if rate_limit_seconds is None else max(0.0, float(rate_limit_seconds))
        )
        self._sleeper = sleeper
        self._last_errors: Tuple[Tuple[str, str], ...] = ()
        self.last_source_statuses: Mapping[str, str] = {}
        self.last_collection_status = "empty"
        self.last_records_read = 0
        self.last_excluded_non_filings = 0
        self.last_failure_details: Tuple[Mapping[str, str], ...] = ()

    @classmethod
    def configuration_error(cls) -> Optional[str]:
        path = os.environ.get("CA_IR_CONFIG_PATH", "").strip()
        if not path:
            return "CA_IR_CONFIG_PATH is not configured."
        if not Path(path).is_file():
            return f"CA_IR_CONFIG_PATH does not exist: {path}"
        try:
            load_sources_from_path(Path(path))
        except (OSError, ValueError, json.JSONDecodeError) as error:
            return f"CA IR configuration is invalid: {_error_text(error)}"
        return None

    @classmethod
    def from_environment(cls) -> "CaIrConnector":
        error = cls.configuration_error()
        if error:
            raise ConnectorUnavailableError(error)
        return cls(sources=load_sources_from_path(
            Path(os.environ["CA_IR_CONFIG_PATH"])
        ))

    @property
    def last_errors(self) -> Tuple[Tuple[str, str], ...]:
        return self._last_errors

    def collect(self, request: CollectionRequest) -> List[InformationItem]:
        targets = {
            normalize_ca_ticker(ticker)
            for ticker in request.tickers
            if request.market_for(ticker) == MARKET_CA
        }
        configured = tuple(source for source in self._sources if source.ticker in targets)
        if not configured:
            self._set_status("empty", (), {}, 0, 0)
            return []

        collected_at = datetime.now(timezone.utc)
        statuses: dict[str, str] = {}
        failures: List[Tuple[str, str]] = []
        items: List[InformationItem] = []
        records_read = 0
        excluded = 0
        for source_index, source in enumerate(configured):
            try:
                if source_index and self._rate_limit_seconds:
                    self._sleeper(self._rate_limit_seconds)
                records: List[_Record] = []
                seen_record_ids: set[str] = set()
                for page_index, page_url in enumerate(
                    (source.feed_url,) + source.page_urls
                ):
                    if page_index and self._rate_limit_seconds:
                        self._sleeper(self._rate_limit_seconds)
                    response = self._fetch_with_retry(page_url)
                    page_records = _parse(source, response.text)
                    duplicate_ids = {
                        record.external_id for record in page_records
                        if record.external_id in seen_record_ids
                    }
                    if duplicate_ids:
                        raise CaIrDataError(
                            "configured pagination repeated filing ids"
                        )
                    seen_record_ids.update(
                        record.external_id for record in page_records
                    )
                    records.extend(page_records)
                records_read += len(records)
                accepted = [record for record in records if _is_filing(source, record)]
                excluded += len(records) - len(accepted)
                items.extend(
                    _to_item(source, record, collected_at)
                    for record in accepted
                    if request.start_date <= record.published.astimezone(
                        ZoneInfo(source.timezone)
                    ).date() <= request.end_date
                )
                statuses[source.source_id] = "partial" if accepted else "empty"
            except Exception as error:
                # A source is atomic: errors never leave partly parsed entries.
                statuses[source.source_id] = "unavailable"
                failures.append((source.ticker, f"{source.source_id}: {_error_text(error)}"))

        unavailable = any(value == "unavailable" for value in statuses.values())
        healthy = any(value != "unavailable" for value in statuses.values())
        # Even a healthy issuer feed is a rolling subset, not a complete
        # regulator-equivalent date window. Records are therefore partial,
        # while a structurally valid feed with genuinely no matching rows is
        # still distinguishable as empty.
        status = "partial" if unavailable and healthy else "unavailable" if unavailable else "partial" if items else "empty"
        self._set_status(status, failures, statuses, records_read, excluded)
        return items

    def _fetch_with_retry(self, url: str) -> CaIrResponse:
        for attempt in range(self._retry_attempts):
            try:
                return _as_response(self._fetcher(url))
            except CaIrRequestError as error:
                message = _error_text(error)
                blocked = any(code in message for code in ("HTTP 403", "HTTP 429"))
                if blocked or attempt + 1 >= self._retry_attempts:
                    raise
                self._sleeper(min(2 ** attempt, 4))
        raise CaIrRequestError("IR request retry loop ended unexpectedly")

    def _set_status(
        self,
        status: str,
        errors: Sequence[Tuple[str, str]],
        source_statuses: Mapping[str, str],
        records_read: int,
        excluded: int,
    ) -> None:
        self.last_collection_status = status
        self._last_errors = tuple(errors)
        self.last_source_statuses = dict(source_statuses)
        self.last_records_read = records_read
        self.last_excluded_non_filings = excluded
        by_source = {source.source_id: source for source in self._sources}
        details: List[Mapping[str, str]] = []
        for _ticker, message in errors:
            source_id = message.split(":", 1)[0]
            configured = by_source.get(source_id)
            details.append({
                "feed": source_id,
                "url": configured.feed_url if configured else "",
                "message": message,
            })
        self.last_failure_details = tuple(details)


def _fetch_text(url: str) -> CaIrResponse:
    request = Request(url, headers={"User-Agent": _USER_AGENT, "Accept": "application/xml, application/json, text/html;q=0.9"})
    try:
        with urlopen(request, timeout=20) as response:  # nosec B310: URL was config validated
            charset = response.headers.get_content_charset() or "utf-8"
            return CaIrResponse(response.read().decode(charset, errors="strict"), dict(response.headers.items()))
    except HTTPError as error:
        raise CaIrRequestError(f"HTTP {error.code}") from error
    except (URLError, TimeoutError, socket.timeout, OSError) as error:
        raise CaIrRequestError(str(error) or error.__class__.__name__) from error


def _as_response(value: Any) -> CaIrResponse:
    if isinstance(value, CaIrResponse):
        return value
    if isinstance(value, str):
        return CaIrResponse(value)
    if isinstance(value, tuple) and len(value) == 2:
        return CaIrResponse(str(value[0]), dict(value[1]))
    raise CaIrRequestError("fetcher did not return text")


def _parse(source: CaIrSource, text: str) -> List[_Record]:
    try:
        if source.format == "rss":
            return _parse_rss(source, text)
        if source.format == "atom":
            return _parse_atom(source, text)
        if source.format == "json":
            return _parse_json(source, text)
        if source.format == "sitemap":
            return _parse_sitemap(source, text)
        return _parse_html(source, text)
    except CaIrError:
        raise
    except (ElementTree.ParseError, json.JSONDecodeError, UnicodeError, ValueError, TypeError) as error:
        raise CaIrDataError(f"{source.format} response structure changed or is malformed") from error


def _parse_rss(source: CaIrSource, text: str) -> List[_Record]:
    root = ElementTree.fromstring(text)
    if _local(root.tag) != "rss":
        raise CaIrDataError("RSS root is required")
    channel = next((node for node in root if _local(node.tag) == "channel"), None)
    if channel is None:
        raise CaIrDataError("RSS channel is required")
    records: List[_Record] = []
    for item in (node for node in channel if _local(node.tag) == "item"):
        title = _child_text(item, "title")
        link = _child_text(item, "link")
        published_raw = _child_text(item, "pubDate")
        identifier = _child_text(item, "guid") or link
        attachments = tuple(source.permits_url(node.attrib.get("url", "")) for node in item if _local(node.tag) == "enclosure")
        records.append(_record(source, identifier, title, published_raw, link, attachments, _child_text(item, "description"), {"tag": "item", "title": title, "link": link, "pubDate": published_raw}))
    return records


def _parse_atom(source: CaIrSource, text: str) -> List[_Record]:
    root = ElementTree.fromstring(text)
    if _local(root.tag) != "feed":
        raise CaIrDataError("Atom feed root is required")
    records: List[_Record] = []
    for entry in (node for node in root if _local(node.tag) == "entry"):
        identifier = _child_text(entry, "id")
        title = _child_text(entry, "title")
        published_raw = _child_text(entry, "published") or _child_text(entry, "updated")
        primary = ""
        attachments: List[str] = []
        for node in entry:
            if _local(node.tag) != "link":
                continue
            href = node.attrib.get("href", "")
            relation = node.attrib.get("rel", "alternate").lower()
            if relation == "enclosure":
                attachments.append(source.permits_url(href))
            elif relation in {"", "alternate"} and not primary:
                primary = source.permits_url(href)
        records.append(_record(source, identifier, title, published_raw, primary, tuple(attachments), _child_text(entry, "summary") or _child_text(entry, "content"), {"tag": "entry", "id": identifier, "title": title, "published": published_raw, "url": primary}))
    return records


def _parse_json(source: CaIrSource, text: str) -> List[_Record]:
    payload = json.loads(text)
    if not isinstance(payload, Mapping) or not isinstance(payload.get("items"), list):
        raise CaIrDataError("JSON feed must be an object with an items list")
    records: List[_Record] = []
    for item in payload["items"]:
        if not isinstance(item, Mapping):
            raise CaIrDataError("JSON item must be an object")
        title = _text(item.get("title"))
        published_raw = _text(item.get("published") or item.get("published_at"))
        url = _text(item.get("url") or item.get("link"))
        identifier = _text(item.get("id") or item.get("guid") or item.get("external_id") or url)
        attachments = _json_attachments(source, item.get("attachments"))
        records.append(_record(source, identifier, title, published_raw, url, attachments, _optional_text(item.get("summary") or item.get("description")), dict(item)))
    return records


def _parse_sitemap(source: CaIrSource, text: str) -> List[_Record]:
    root = ElementTree.fromstring(text)
    if _local(root.tag) != "urlset":
        raise CaIrDataError("sitemap urlset root is required")
    records: List[_Record] = []
    for node in (entry for entry in root if _local(entry.tag) == "url"):
        loc = _child_text(node, "loc")
        lastmod = _child_text(node, "lastmod")
        title = urlparse(loc).path.rstrip("/").rsplit("/", 1)[-1].replace("-", " ")
        records.append(_record(source, loc, title, lastmod, loc, (), None, {"tag": "url", "loc": loc, "lastmod": lastmod}))
    return records


class _ContractHtmlParser(HTMLParser):
    """HTML reader for an intentionally tiny, explicit issuer-page contract."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.records: List[dict[str, Any]] = []
        self._current: Optional[dict[str, Any]] = None
        self._title_parts: List[str] = []
        self._anchor_parts: List[str] = []
        self._anchor_href = ""

    def handle_starttag(self, tag: str, attrs: List[Tuple[str, Optional[str]]]) -> None:
        values = dict(attrs)
        if tag == "article":
            if self._current is not None:
                raise CaIrDataError("nested filing contract article")
            self._current = {"id": values.get("data-id", ""), "title": values.get("data-title", ""), "published": values.get("data-published", ""), "url": values.get("data-url", ""), "attachments": []}
        elif self._current is not None and tag in {"h1", "h2", "h3"}:
            self._title_parts = []
        elif self._current is not None and tag == "time" and values.get("datetime"):
            self._current["published"] = values["datetime"]
        elif tag == "a" and self._current is not None:
            href = values.get("href") or ""
            if "data-ca-ir-attachment" in values or href.lower().endswith(
                (".pdf", ".doc", ".docx", ".xls", ".xlsx", ".zip")
            ):
                self._current["attachments"].append(href)
            else:
                self._anchor_href = href
                self._anchor_parts = []

    def handle_data(self, data: str) -> None:
        if self._current is not None and self._title_parts is not None:
            self._title_parts.append(data)
        if self._anchor_href:
            self._anchor_parts.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag in {"h1", "h2", "h3"} and self._current is not None:
            title = " ".join("".join(self._title_parts).split())
            if title and not self._current["title"]:
                self._current["title"] = title
            self._title_parts = []
        elif tag == "a" and self._current is not None and self._anchor_href:
            text = " ".join("".join(self._anchor_parts).split())
            if not self._current["url"]:
                self._current["url"] = self._anchor_href
            if not self._current["id"]:
                self._current["id"] = self._anchor_href
            if text and not self._current["title"]:
                self._current["title"] = text
            self._anchor_href = ""
            self._anchor_parts = []
        elif tag == "article" and self._current is not None:
            self.records.append(self._current)
            self._current = None

    def close(self) -> None:
        super().close()
        if self._current is not None:
            raise CaIrDataError("unclosed filing contract article")


def _parse_html(source: CaIrSource, text: str) -> List[_Record]:
    parser = _ContractHtmlParser()
    parser.feed(text)
    parser.close()
    if not parser.records:
        raise CaIrDataError("HTML page lacks data-ca-ir-filing contract records")
    return [
        _record(source, _text(record["id"]), _text(record["title"]), _text(record["published"]), _text(record["url"]), tuple(source.permits_url(value) for value in record["attachments"]), None, record)
        for record in parser.records
    ]


def _record(source: CaIrSource, identifier: str, title: str, published_raw: str, url: str, attachments: Tuple[str, ...], summary: Optional[str], raw: Mapping[str, Any]) -> _Record:
    identifier, title, published_raw, url = map(_text, (identifier, title, published_raw, url))
    if not all((identifier, title, published_raw, url)):
        raise CaIrDataError("filing record requires id, title, published date, and URL")
    return _Record(identifier, title, _parse_date(published_raw, source.timezone), published_raw, source.permits_url(url), attachments, summary, raw)


def _parse_date(value: str, timezone_name: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        try:
            parsed = parsedate_to_datetime(value)
        except (TypeError, ValueError) as error:
            raise CaIrDataError("filing published date is required and must be parseable") from error
    if isinstance(parsed, datetime):
        return parsed.replace(tzinfo=ZoneInfo(timezone_name)) if parsed.tzinfo is None else parsed.astimezone(timezone.utc)
    return datetime.combine(parsed, time(12), tzinfo=ZoneInfo(timezone_name))


def _is_filing(source: CaIrSource, record: _Record) -> bool:
    text = f"{record.title} {record.url}".casefold()
    return any(term in text for term in source.filing_terms)


def _to_item(source: CaIrSource, record: _Record, collected_at: datetime) -> InformationItem:
    filing_type = classify_ca_filing(record.title)
    return InformationItem(
        source="ca_ir",
        source_type="regulatory_filing",
        external_id=f"{source.source_id}:{record.external_id}",
        tickers=(source.ticker,),
        issuer=source.issuer,
        published_at=record.published,
        title=record.title,
        document_type=filing_type,
        url=record.url,
        collected_at=collected_at,
        raw_metadata={
            **build_raw_provenance(official_source_id=record.external_id, official_source_url=record.url, retrieval_url=source.feed_url, raw_payload=record.raw, raw_payload_format=f"{source.format}_parsed_record", classification_code="issuer_ir_filing", classification_label="Issuer-configured IR filing", published_at_raw=record.published_raw, published_timezone=source.timezone),
            "source_tier": 2,
            "source_tier_label": "issuer_ir",
            "provenance_tier": 2,
            "issuer_allowlisted": True,
            "issuer_ticker": source.ticker,
            "issuer_name": source.issuer,
            "issuer_exchange": source.exchange,
            "source_id": source.source_id,
            "source_format": source.format,
            "retrieval_urls": [source.feed_url, *source.page_urls],
            "attachments": list(record.attachments),
            "classification_scope": "issuer_configured_filing_terms",
            "filing_type": filing_type,
            "is_official": True,
            "officiality": "issuer_published",
            "cross_verified": False,
            "attachments_may_be_missing": not bool(record.attachments),
        },
        market=MARKET_CA,
        summary=record.summary,
        effective_at=record.published,
    )


def _json_attachments(source: CaIrSource, value: Any) -> Tuple[str, ...]:
    if value is None:
        return ()
    values = [value] if isinstance(value, (str, Mapping)) else value
    if not isinstance(values, list):
        raise CaIrDataError("JSON attachments must be a URL or list")
    urls: List[str] = []
    for attachment in values:
        url = attachment if isinstance(attachment, str) else attachment.get("url") or attachment.get("href") if isinstance(attachment, Mapping) else ""
        if not _text(url):
            raise CaIrDataError("JSON attachment requires a URL")
        urls.append(source.permits_url(_text(url)))
    return tuple(urls)


def _child_text(node: ElementTree.Element, local_name: str) -> str:
    child = next((entry for entry in node if _local(entry.tag) == local_name), None)
    return _text(child.text if child is not None else "")


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _text(value: Any) -> str:
    return str(value or "").strip()


def _optional_text(value: Any) -> Optional[str]:
    result = _text(value)
    return result or None


def _error_text(error: Exception) -> str:
    return str(error).strip() or error.__class__.__name__


def classify_ca_filing(title: str) -> str:
    """Map an issuer disclosure title to the Canadian filing taxonomy."""
    value = " ".join(str(title or "").casefold().split())
    rules = (
        ("technical_report", ("technical report", "ni 43-101")),
        ("prospectus", ("prospectus", "offering memorandum")),
        ("annual_report", ("annual report", "annual financial", "40-f", "20-f")),
        ("interim_report", ("interim report", "interim financial", "quarterly report")),
        ("financial_results", ("financial results", "earnings", "results for the")),
        ("acquisition_disposal", ("acquisition", "merger", "disposition", "asset sale")),
        ("financing", ("financing", "private placement", "public offering", "debt offering")),
        ("management_change", ("appoints", "appointment", "resignation", "chief executive", "director change")),
        ("share_buyback", ("share buyback", "normal course issuer bid", "repurchase")),
        ("dividend", ("dividend", "distribution")),
        ("trading_halt", ("trading halt", "halted", "resume trading", "reinstatement")),
        ("material_change", ("material change", "material contract", "project update")),
    )
    for filing_type, terms in rules:
        if any(term in value for term in terms):
            return filing_type
    return "other_filing"


def load_sources_from_path(path: Path) -> Tuple[CaIrSource, ...]:
    """Load a strict, reviewable local issuer-feed configuration."""
    with path.open("r", encoding="utf-8") as handle:
        payload = json.load(handle)
    if not isinstance(payload, Mapping) or set(payload) != {"schema", "sources"}:
        raise ValueError("CA IR config must contain only schema and sources")
    if payload.get("schema") != CONFIG_SCHEMA:
        raise ValueError(f"CA IR config schema must be {CONFIG_SCHEMA}")
    rows = payload.get("sources")
    if not isinstance(rows, list) or not rows:
        raise ValueError("CA IR config sources must be a non-empty list")
    sources: List[CaIrSource] = []
    for row in rows:
        if not isinstance(row, Mapping):
            raise ValueError("CA IR source must be an object")
        allowed = {
            "source_id", "ticker", "issuer", "exchange", "feed_url",
            "format", "url_rules", "filing_terms", "page_urls", "timezone", "publisher_kind",
        }
        if set(row) - allowed:
            raise ValueError("CA IR source contains unknown fields")
        rules = row.get("url_rules")
        if not isinstance(rules, list):
            raise ValueError("CA IR url_rules must be a list")
        sources.append(CaIrSource(
            source_id=str(row.get("source_id") or ""),
            ticker=str(row.get("ticker") or ""),
            issuer=str(row.get("issuer") or ""),
            exchange=str(row.get("exchange") or ""),
            feed_url=str(row.get("feed_url") or ""),
            format=str(row.get("format") or ""),
            url_rules=tuple(CaIrUrlRule(
                host=str(rule.get("host") or ""),
                path_prefix=str(rule.get("path_prefix") or "/"),
            ) for rule in rules if isinstance(rule, Mapping)),
            filing_terms=tuple(str(term) for term in (row.get("filing_terms") or ())),
            page_urls=tuple(str(url) for url in (row.get("page_urls") or ())),
            timezone=str(row.get("timezone") or "America/Toronto"),
            publisher_kind=str(row.get("publisher_kind") or "issuer_ir"),
        ))
    return tuple(sources)
