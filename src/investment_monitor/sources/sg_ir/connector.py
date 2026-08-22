"""Strict, configured SG issuer-IR announcement collector.

This is deliberately not an SGXNET enumerator.  Each issuer feed is reviewed
locally, constrained to HTTPS URL rules, and is therefore an issuer-published
Tier 2 partial source.  A broken template never becomes an empty result.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timezone
from email.utils import parsedate_to_datetime
from html import unescape
from html.parser import HTMLParser
import json
import os
from pathlib import Path
import re
import socket
import time as time_module
from typing import Any, Callable, Iterable, Mapping, Optional, Sequence
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin, urlparse
from urllib.request import Request, urlopen
from xml.etree import ElementTree
from zoneinfo import ZoneInfo

from ...models import CollectionRequest, InformationItem, MARKET_SG
from ...connectors.base import ConnectorUnavailableError
from ...provenance import build_raw_provenance
from ...web_repository import normalize_sg_ticker

SG_IR_CONFIG_SCHEMA = "sg_ir_sources/v1"
_FORMATS = frozenset({"rss", "atom", "json", "sitemap", "html"})
_ADAPTERS = frozenset({
    "article",
    "listedcompany",
    "shareinvestor",
    "singtel_report",
    "ocbc_regulatory",
})
_EXCHANGES = frozenset({"SGX MAINBOARD", "SGX CATALIST", "SGX"})
_ISSUER_TYPES = frozenset({"ordinary_share", "reit", "business_trust", "secondary_listing", "etf"})
SGT = ZoneInfo("Asia/Singapore")


class SgIrError(ValueError):
    pass


class SgIrRequestError(SgIrError):
    pass


class SgIrDataError(SgIrError):
    pass


@dataclass(frozen=True)
class SgIrUrlRule:
    host: str
    path_prefix: str = "/"

    def __post_init__(self) -> None:
        host = str(self.host).strip().lower().rstrip(".")
        prefix = str(self.path_prefix).strip() or "/"
        if not host or any(x in host for x in ("/", ":")) or not prefix.startswith("/"):
            raise ValueError("SgIrUrlRule requires bare host and slash path_prefix")
        object.__setattr__(self, "host", host)
        object.__setattr__(self, "path_prefix", prefix.rstrip("/") or "/")

    def permits(self, value: str) -> bool:
        parsed = urlparse(value)
        path = parsed.path or "/"
        return (parsed.scheme == "https" and not parsed.username and not parsed.password
                and parsed.port in (None, 443) and (parsed.hostname or "").lower().rstrip(".") == self.host
                and (self.path_prefix == "/" or path == self.path_prefix or path.startswith(self.path_prefix + "/")))


@dataclass(frozen=True)
class SgIrSource:
    source_id: str
    ticker: str
    issuer: str
    exchange: str
    feed_url: str
    format: str
    url_rules: tuple[SgIrUrlRule, ...]
    filing_terms: tuple[str, ...]
    page_urls: tuple[str, ...] = ()
    adapter: str = "article"
    issuer_type: str = "ordinary_share"
    isin: str = ""
    language: str = "en"
    timezone: str = "Asia/Singapore"

    def __post_init__(self) -> None:
        ticker = normalize_sg_ticker(self.ticker)
        exchange = str(self.exchange).strip().upper()
        fmt, adapter = str(self.format).lower().strip(), str(self.adapter).lower().strip()
        issuer_type = str(self.issuer_type).lower().strip()
        rules = tuple(self.url_rules)
        terms = tuple(str(x).strip().casefold() for x in self.filing_terms if str(x).strip())
        if not all((self.source_id.strip(), ticker, self.issuer.strip())):
            raise ValueError("SgIrSource requires source_id, ticker and issuer")
        if exchange not in _EXCHANGES or fmt not in _FORMATS or adapter not in _ADAPTERS or issuer_type not in _ISSUER_TYPES:
            raise ValueError("SgIrSource has unsupported exchange, format, adapter, or issuer_type")
        if not rules or not terms or not any(rule.permits(self.feed_url) for rule in rules):
            raise ValueError("SgIrSource requires allowlisted feed and filing_terms")
        if len(self.page_urls) > 99 or any(not any(rule.permits(url) for rule in rules) for url in self.page_urls):
            raise ValueError("SgIrSource page_urls exceed cap or allowlist")
        try: ZoneInfo(self.timezone)
        except Exception as error: raise ValueError("SgIrSource timezone must be IANA") from error
        object.__setattr__(self, "ticker", ticker); object.__setattr__(self, "exchange", exchange)
        object.__setattr__(self, "format", fmt); object.__setattr__(self, "adapter", adapter)
        object.__setattr__(self, "issuer_type", issuer_type); object.__setattr__(self, "url_rules", rules)
        object.__setattr__(self, "filing_terms", terms)

    def url(self, value: str, base: Optional[str] = None) -> str:
        result = urljoin(base or self.feed_url, str(value).strip())
        if not any(rule.permits(result) for rule in self.url_rules):
            raise SgIrDataError("record URL is outside reviewed issuer allowlist")
        return result


@dataclass(frozen=True)
class _Record:
    ident: str; title: str; published: datetime; raw_date: str; url: str
    attachments: tuple[str, ...] = (); summary: Optional[str] = None


class SgIrConnector:
    name = "sg_ir"
    provider = "Audited Singapore investor-relations feeds (Tier 2)"
    source_type = "regulatory_filing"
    coverage_level = "tier_2_issuer_ir_partial"
    coverage_kind = "feed_snapshot"
    max_lookback_days = 31

    def __init__(self, *, sources: Iterable[SgIrSource] = (), fetcher: Optional[Callable[[str], Any]] = None,
                 retry_attempts: int = 3, rate_limit_seconds: Optional[float] = None,
                 sleeper: Callable[[float], None] = time_module.sleep) -> None:
        self._sources = tuple(sources)
        if len({x.source_id for x in self._sources}) != len(self._sources): raise ValueError("duplicate SG IR source_id")
        self._fetcher = fetcher or _fetch
        self._retry_attempts, self._delay, self._sleeper = max(1, int(retry_attempts)), (0.25 if fetcher is None else 0.0) if rate_limit_seconds is None else max(0.0, rate_limit_seconds), sleeper
        self._last_errors: tuple[tuple[str, str], ...] = (); self.last_source_statuses: Mapping[str, str] = {}
        self.last_collection_status = "empty"; self.last_records_read = 0; self.last_excluded_non_filings = 0

    @classmethod
    def configuration_error(cls) -> Optional[str]:
        path = os.environ.get("SG_IR_CONFIG_PATH", "").strip()
        if not path:
            return None
        try: load_sources_from_path(Path(path))
        except (OSError, ValueError, json.JSONDecodeError) as error: return f"SG IR configuration is invalid: {error}"
        return None

    @classmethod
    def from_environment(cls) -> "SgIrConnector":
        path = os.environ.get("SG_IR_CONFIG_PATH", "").strip()
        sources = list(builtin_sg_ir_sources())
        if not path:
            return cls(sources=sources)
        try:
            sources.extend(load_sources_from_path(Path(path)))
            return cls(sources=sources)
        except (OSError, ValueError, json.JSONDecodeError) as error:
            raise ConnectorUnavailableError(
                f"SG IR is not connected: {error}"
            ) from error

    @property
    def last_errors(self) -> tuple[tuple[str, str], ...]: return self._last_errors

    def collect(self, request: CollectionRequest) -> list[InformationItem]:
        targets = {normalize_sg_ticker(t) for t in request.tickers if request.market_for(t) == MARKET_SG}
        sources = tuple(x for x in self._sources if x.ticker in targets)
        if not sources: self._set("empty", (), {}, 0, 0); return []
        items: list[InformationItem] = []; statuses: dict[str, str] = {}; errors: list[tuple[str, str]] = []; read = excluded = 0
        now = datetime.now(timezone.utc)
        for source_no, source in enumerate(sources):
            try:
                if source_no and self._delay: self._sleeper(self._delay)
                records: list[_Record] = []
                seen: set[str] = set()
                for page_no, url in enumerate((source.feed_url, *source.page_urls)):
                    if page_no and self._delay: self._sleeper(self._delay)
                    page = _parse(source, self._retry_fetch(url))
                    ids = {r.ident for r in page}
                    if len(ids) != len(page) or ids & seen: raise SgIrDataError("configured pagination repeated announcement IDs")
                    seen |= ids; records.extend(page)
                read += len(records); accepted = [r for r in records if _is_filing(source, r)]
                excluded += len(records) - len(accepted)
                items.extend(_item(source, r, now) for r in accepted if request.start_date <= r.published.astimezone(SGT).date() <= request.end_date)
                statuses[source.source_id] = "partial" if accepted else "empty"
            except Exception as error:
                statuses[source.source_id] = "unavailable"; errors.append((source.ticker, f"{source.source_id}: {error or error.__class__.__name__}"))
        healthy, bad = any(x != "unavailable" for x in statuses.values()), any(x == "unavailable" for x in statuses.values())
        status = "partial" if healthy else "unavailable" if bad else "empty"
        self._set(status, errors, statuses, read, excluded); return items

    def _retry_fetch(self, url: str) -> str:
        for attempt in range(self._retry_attempts):
            try: return _text_response(self._fetcher(url))
            except SgIrRequestError as error:
                if "HTTP 403" in str(error) or "HTTP 429" in str(error) or attempt + 1 == self._retry_attempts: raise
                self._sleeper(min(4.0, 2 ** attempt))
        raise SgIrRequestError("IR retry loop ended unexpectedly")

    def _set(self, status: str, errors: Sequence[tuple[str, str]], statuses: Mapping[str, str], read: int, excluded: int) -> None:
        self.last_collection_status, self._last_errors, self.last_source_statuses = status, tuple(errors), dict(statuses)
        self.last_records_read, self.last_excluded_non_filings = read, excluded


def _fetch(url: str) -> str:
    try:
        with urlopen(Request(url, headers={"User-Agent": "InvestmentMonitor/sg-ir", "Accept": "application/xml,application/json,text/html;q=0.9"}), timeout=20) as response: # nosec B310 config is validated
            return str(response.read().decode(response.headers.get_content_charset() or "utf-8", errors="strict"))
    except HTTPError as error: raise SgIrRequestError(f"HTTP {error.code}") from error
    except (URLError, TimeoutError, socket.timeout, OSError) as error: raise SgIrRequestError(str(error) or error.__class__.__name__) from error


def _text_response(value: Any) -> str:
    if isinstance(value, str): return value
    if isinstance(value, bytes): return value.decode("utf-8")
    raise SgIrRequestError("fetcher did not return text")


def _parse(source: SgIrSource, text: str) -> list[_Record]:
    try:
        if source.format == "rss": return _rss(source, text)
        if source.format == "atom": return _atom(source, text)
        if source.format == "json": return _json(source, text)
        if source.format == "sitemap": return _sitemap(source, text)
        return _html(source, text)
    except SgIrError: raise
    except (ElementTree.ParseError, json.JSONDecodeError, TypeError, ValueError, UnicodeError) as error:
        raise SgIrDataError(f"{source.format} response structure changed or malformed") from error


def _rss(source: SgIrSource, text: str) -> list[_Record]:
    root = ElementTree.fromstring(text)
    if _local(root.tag) != "rss": raise SgIrDataError("RSS root required")
    channel = next((x for x in root if _local(x.tag) == "channel"), None)
    if channel is None: raise SgIrDataError("RSS channel required")
    out=[]
    for node in [x for x in channel if _local(x.tag)=="item"]:
        attachments=tuple(source.url(x.attrib.get("url", "")) for x in node if _local(x.tag)=="enclosure")
        out.append(_record(source, _child(node,"guid") or _child(node,"link"), _child(node,"title"), _child(node,"pubDate"), _child(node,"link"), attachments, _child(node,"description")))
    return out


def _atom(source: SgIrSource, text: str) -> list[_Record]:
    root=ElementTree.fromstring(text)
    if _local(root.tag)!="feed": raise SgIrDataError("Atom feed root required")
    out=[]
    for node in [x for x in root if _local(x.tag)=="entry"]:
        links=[x.attrib.get("href","") for x in node if _local(x.tag)=="link" and x.attrib.get("href")]
        if not links: raise SgIrDataError("Atom entry link required")
        out.append(_record(source,_child(node,"id") or links[0],_child(node,"title"),_child(node,"published") or _child(node,"updated"),links[0],tuple(source.url(x) for x in links[1:]),_child(node,"summary") or _child(node,"content")))
    return out


def _json(source: SgIrSource, text: str) -> list[_Record]:
    payload=json.loads(text); rows=payload.get("items", payload.get("data", payload)) if isinstance(payload, Mapping) else payload
    if not isinstance(rows,list): raise SgIrDataError("JSON list/items/data required")
    out=[]
    for row in rows:
        if not isinstance(row,Mapping): raise SgIrDataError("JSON item must be object")
        ident=str(row.get("id") or row.get("guid") or row.get("url") or row.get("link") or "")
        url=str(row.get("url") or row.get("link") or row.get("document_url") or "")
        title=str(row.get("title") or row.get("headline") or "")
        when=str(row.get("published_at") or row.get("published") or row.get("date") or row.get("datetime") or "")
        raw_attachments=row.get("attachments") or row.get("files") or []
        if isinstance(raw_attachments,(str,Mapping)): raw_attachments=[raw_attachments]
        if not isinstance(raw_attachments,list): raise SgIrDataError("JSON attachments must be list")
        attachments=tuple(source.url(x if isinstance(x,str) else str(x.get("url") or x.get("href") or "")) for x in raw_attachments)
        out.append(_record(source,ident,title,when,url,attachments,str(row.get("summary") or row.get("description") or "") or None))
    return out


def _sitemap(source: SgIrSource, text: str) -> list[_Record]:
    root=ElementTree.fromstring(text)
    if _local(root.tag)!="urlset": raise SgIrDataError("sitemap urlset root required")
    return [_record(source,_child(x,"loc"),_title_from_url(_child(x,"loc")),_child(x,"lastmod"),_child(x,"loc"),()) for x in root if _local(x.tag)=="url"]


class _AnchorParser(HTMLParser):
    """Bind one date and one announcement link within a template row."""

    def __init__(self, adapter: str) -> None:
        super().__init__()
        self.adapter = adapter
        self.rows: list[tuple[str, str, str]] = []
        self._depth = 0
        self._container_tag = ""
        self._href = ""
        self._in_link = False
        self._text: list[str] = []
        self._date = ""
        self._in_date = False
        self._date_parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, Optional[str]]]) -> None:
        attr_map = {key: value or "" for key, value in attrs}
        classes = attr_map.get("class", "").casefold()
        is_container = tag == "article"
        if self.adapter == "listedcompany":
            is_container = tag in {"div", "li", "tr"} and any(
                marker in classes for marker in ("announcement", "news-row", "release-row")
            )
        elif self.adapter == "shareinvestor":
            is_container = tag in {"div", "li", "tr"} and any(
                marker in classes for marker in ("announcement", "newsitem", "press-release")
            )
        elif self.adapter == "article":
            is_container = tag == "article" or (
                tag in {"li", "div"} and "announcement" in classes
            )
        if self._depth:
            self._depth += 1
        elif is_container:
            self._depth = 1
            self._container_tag = tag
            self._href = ""
            self._text = []
            self._date = ""
        if not self._depth:
            return
        if tag == "a" and attr_map.get("href") and not self._href:
            self._href = attr_map["href"]
            self._text = []
            self._in_link = True
        if tag == "time" or "date" in classes:
            self._in_date = True
            self._date_parts = []
            if attr_map.get("datetime"):
                self._date = attr_map["datetime"]

    def handle_data(self, data: str) -> None:
        if not self._depth:
            return
        if self._in_link:
            self._text.append(data)
        if self._in_date and not self._date:
            self._date_parts.append(data)

    def handle_endtag(self, tag: str) -> None:
        if not self._depth:
            return
        if self._in_date and tag in {"time", "span", "div", "td"}:
            if not self._date:
                self._date = " ".join("".join(self._date_parts).split())
            self._in_date = False
            self._date_parts = []
        if tag == "a":
            self._in_link = False
        self._depth -= 1
        if self._depth == 0:
            if self._href:
                self.rows.append((
                    self._href,
                    " ".join("".join(self._text).split()),
                    self._date,
                ))
            self._container_tag = ""
            self._href = ""
            self._in_link = False
            self._text = []
            self._date = ""


def _html(source: SgIrSource,text:str)->list[_Record]:
    if source.adapter == "singtel_report":
        return _singtel_report(source, text)
    if source.adapter == "ocbc_regulatory":
        return _ocbc_regulatory(source, text)
    parser=_AnchorParser(source.adapter); parser.feed(text)
    if not parser.rows: raise SgIrDataError(f"{source.adapter} page has no announcement links")
    out=[]
    for href,title,when in parser.rows:
        if not title: continue
        # Hosted templates usually expose date in sibling text; a missing date is
        # unsafe because date windows would otherwise silently over-collect.
        if not when: raise SgIrDataError("HTML announcement link has no parseable date")
        url=source.url(href)
        out.append(_record(source,url,title,when,url,()))
    if not out: raise SgIrDataError("HTML contained no usable announcement links")
    return out


class _DatamodelParser(HTMLParser):
    """Extract a named component's public JSON datamodel attribute."""

    def __init__(self, component: str) -> None:
        super().__init__(convert_charrefs=True)
        self.component = component.casefold()
        self.values: list[str] = []

    def handle_starttag(
        self, tag: str, attrs: list[tuple[str, Optional[str]]]
    ) -> None:
        attributes = {key.casefold(): value or "" for key, value in attrs}
        if attributes.get("component", "").casefold() == self.component:
            value = attributes.get("datamodel", "").strip()
            if not value:
                raise SgIrDataError("issuer IR component has no datamodel")
            self.values.append(value)


def _singtel_report(source: SgIrSource, text: str) -> list[_Record]:
    parser = _DatamodelParser("ReportThreeColumns")
    parser.feed(text)
    if len(parser.values) != 1:
        raise SgIrDataError("Singtel IR page must contain one report datamodel")
    try:
        payload = json.loads(unescape(parser.values[0]))
    except (TypeError, json.JSONDecodeError) as error:
        raise SgIrDataError("Singtel report datamodel is malformed") from error
    if not isinstance(payload, Mapping):
        raise SgIrDataError("Singtel report datamodel must be an object")
    years = payload.get("yearReports")
    if not isinstance(years, list) or not years:
        raise SgIrDataError("Singtel report datamodel has no yearReports")
    records: list[_Record] = []
    seen_years: set[str] = set()
    for year in years:
        if not isinstance(year, Mapping):
            raise SgIrDataError("Singtel yearReports row must be an object")
        header = str(year.get("header") or "").strip()
        rows = year.get("dataRecords")
        if not header.isdigit() or len(header) != 4 or header in seen_years:
            raise SgIrDataError("Singtel yearReports header is invalid or duplicate")
        if not isinstance(rows, list):
            raise SgIrDataError("Singtel yearReports dataRecords must be a list")
        seen_years.add(header)
        for row in rows:
            if not isinstance(row, Mapping):
                raise SgIrDataError("Singtel announcement row must be an object")
            title = " ".join(unescape(str(row.get("title") or "")).split())
            url = unescape(str(row.get("fileLink") or "").strip())
            published = str(row.get("date") or "").strip()
            record = _record(
                source,
                f"{url}|{published}|{title}",
                title,
                published,
                url,
                (source.url(url),),
            )
            if str(record.published.astimezone(SGT).year) != header:
                raise SgIrDataError("Singtel announcement date disagrees with year header")
            records.append(record)
    if not records:
        raise SgIrDataError("Singtel report datamodel contains no announcements")
    return records


class _OcbcRegulatoryParser(HTMLParser):
    """Read OCBC's year-grouped date marker / PDF list."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._year = ""
        self._ul_depth = 0
        self._li_depth = 0
        self._anchor_seen = False
        self._href = ""
        self._text: list[str] = []
        self.rows: list[tuple[str, str, str]] = []

    def handle_starttag(
        self, tag: str, attrs: list[tuple[str, Optional[str]]]
    ) -> None:
        attributes = {key.casefold(): value or "" for key, value in attrs}
        if (
            tag == "ul"
            and attributes.get("data-content", "").isdigit()
            and "accordion__list" in attributes.get("class", "").split()
        ):
            if self._ul_depth:
                raise SgIrDataError("OCBC regulatory year lists must not nest")
            self._year = attributes["data-content"]
            self._ul_depth = 1
            return
        if self._ul_depth and tag == "ul":
            self._ul_depth += 1
        if not self._year:
            return
        if tag == "li":
            if self._li_depth:
                raise SgIrDataError("OCBC regulatory filing rows must not nest")
            self._li_depth = 1
            self._anchor_seen = False
            self._href = ""
            self._text = []
        elif self._li_depth and tag == "a" and not self._anchor_seen:
            self._anchor_seen = True
            self._href = attributes.get("href", "").strip()

    def handle_data(self, data: str) -> None:
        if self._li_depth and self._anchor_seen:
            self._text.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag == "li" and self._li_depth:
            text = " ".join("".join(self._text).split())
            if not self._anchor_seen and not text:
                self._li_depth = 0
                self._anchor_seen = False
                self._href = ""
                self._text = []
                return
            if not self._anchor_seen or not text:
                raise SgIrDataError("OCBC regulatory list row is incomplete")
            self.rows.append((self._year, self._href, text))
            self._li_depth = 0
            self._anchor_seen = False
            self._href = ""
            self._text = []
        elif tag == "ul" and self._ul_depth:
            self._ul_depth -= 1
            if not self._ul_depth:
                self._year = ""


def _ocbc_regulatory(source: SgIrSource, text: str) -> list[_Record]:
    parser = _OcbcRegulatoryParser()
    parser.feed(text)
    if not parser.rows:
        raise SgIrDataError("OCBC regulatory page has no year-grouped rows")
    current_date = ""
    current_year = ""
    records: list[_Record] = []
    years: set[str] = set()
    for year, href, label in parser.rows:
        if len(year) != 4:
            raise SgIrDataError("OCBC regulatory year is invalid")
        years.add(year)
        if href.casefold() in {"", "na"}:
            try:
                parsed = _date(label, source.timezone)
            except SgIrDataError as error:
                # One historical OCBC section uses an empty-href descriptive
                # heading rather than a date. Its following filenames carry
                # explicit YYYY MM DD prefixes, which are validated below.
                if re.match(r"^\s*\d", label):
                    raise SgIrDataError(
                        "OCBC date marker is invalid "
                        f"(year={year}, label={label[:80]})"
                    ) from error
                current_date = ""
                current_year = year
                continue
            if str(parsed.astimezone(SGT).year) != year:
                raise SgIrDataError("OCBC date marker disagrees with year group")
            current_date = label
            current_year = year
            continue
        if current_year != year:
            raise SgIrDataError(
                "OCBC regulatory document has no preceding date "
                f"(year={year}, href={href[:80]})"
            )
        published = current_date or _ocbc_date_from_url(href, year)
        url = source.url(href)
        if not urlparse(url).path.casefold().endswith(".pdf"):
            raise SgIrDataError("OCBC regulatory document is not a PDF")
        records.append(_record(
            source,
            f"{url}|{published}|{label}",
            unescape(label),
            published,
            url,
            (url,),
        ))
    if not records or len(years) < 2:
        raise SgIrDataError("OCBC regulatory archive is unexpectedly incomplete")
    return records


def _ocbc_date_from_url(value: str, expected_year: str) -> str:
    match = re.search(
        r"/(20\d{2})[ _-](\d{2})[ _-](\d{2})",
        unescape(urlparse(value).path),
    )
    if not match or match.group(1) != expected_year:
        raise SgIrDataError(
            "OCBC undated section document has no filename date"
        )
    try:
        parsed = date(
            int(match.group(1)), int(match.group(2)), int(match.group(3))
        )
    except ValueError as error:
        raise SgIrDataError("OCBC filename date is invalid") from error
    return parsed.isoformat()


def _record(source:SgIrSource, ident:str,title:str,when:str,url:str,attachments:tuple[str,...],summary:Optional[str]=None)->_Record:
    if not all((str(ident).strip(),str(title).strip(),str(when).strip(),str(url).strip())): raise SgIrDataError("announcement requires id, title, date, URL")
    return _Record(str(ident).strip(),str(title).strip(),_date(str(when),source.timezone),str(when),source.url(url),attachments,summary)

def _date(value:str,timezone_name:str)->datetime:
    try: parsed=datetime.fromisoformat(value.replace("Z","+00:00"))
    except ValueError:
        try: parsed=parsedate_to_datetime(value)
        except (TypeError,ValueError):
            parsed = None
        if parsed is None:
            leading_date = re.match(
                r"^(\d{1,2}\s+[A-Za-z]+\s+\d{4})(?:\s*[-–].*)?$",
                value.strip(),
            )
            date_value = leading_date.group(1) if leading_date else value
            for date_format in ("%d %b %Y", "%d %B %Y", "%d/%m/%Y"):
                try:
                    parsed = datetime.strptime(date_value, date_format).replace(
                        hour=12
                    )
                    break
                except ValueError:
                    continue
        if parsed is None:
            raise SgIrDataError("announcement date must be parseable")
    assert parsed is not None
    if parsed.tzinfo is None: return parsed.replace(tzinfo=ZoneInfo(timezone_name))
    return parsed.astimezone(timezone.utc)
def _child(node:Any,name:str)->str:
    child=next((x for x in node if _local(x.tag)==name),None); return str(child.text or "").strip() if child is not None else ""
def _local(tag:str)->str: return tag.rsplit("}",1)[-1]
def _title_from_url(value:str)->str: return " ".join(urlparse(value).path.rsplit("/",1)[-1].replace("-"," ").split()) or "Announcement"
def _is_filing(source:SgIrSource,record:_Record)->bool: return any(x in f"{record.title} {record.url}".casefold() for x in source.filing_terms)

def classify_sg_filing(title:str)->str:
    value=" ".join(re.sub(r"[^a-z0-9]+", " ", str(title).casefold()).split())
    rules=(("prospectus",("prospectus",)),("offer_document",("offer document","scheme document")),("annual_report",("annual report",)),("sustainability_report",("sustainability",)),("financial_results",("financial result","results for", "earnings")),("acquisition_disposal",("acquisition","acquire","disposal","divestment","sale of","merger")),("financing",("placement","rights issue","financing","notes issue","bond","capital securities")),("capital_change",("capital change","share issue")),("dividend",("dividend","distribution")),("share_buyback",("share buyback","share buy back","share purchase mandate")),("management_change",("appoint","resignation","director")),("trading_halt",("trading halt","suspension")),("trading_resumption",("trading resumption","resume trading")),("general_meeting",("general meeting","agm","egm")),("circular",("circular",)))
    return next((kind for kind,terms in rules if any(x in value for x in terms)),"other_filing")

def _item(source:SgIrSource,r:_Record,collected_at:datetime)->InformationItem:
    filing_type=classify_sg_filing(r.title)
    sgx_id = _sgx_announcement_id((r.url, *r.attachments))
    canonical = f"sgx-id:{sgx_id}" if sgx_id else ""
    discovery_source = (
        "audited_builtin_ir"
        if source.source_id in {
            "singtel-stock-exchange-announcements",
            "ocbc-major-regulatory-announcements",
        }
        else "issuer_ir_config"
    )
    return InformationItem(source="sg_ir",source_type="regulatory_filing",external_id=f"{source.source_id}:{r.ident}",tickers=(source.ticker,),issuer=source.issuer,published_at=r.published,title=r.title,document_type=filing_type,url=r.url,collected_at=collected_at,raw_metadata={**build_raw_provenance(official_source_id=r.ident,official_source_url=r.url,retrieval_url=source.feed_url,raw_payload={"title":r.title,"date":r.raw_date,"attachments":list(r.attachments)},raw_payload_format=f"{source.format}_parsed_record",classification_code="issuer_ir_filing",classification_label="Issuer IR filing",published_at_raw=r.raw_date,published_timezone=source.timezone),"source_tier":2,"source_tier_label":"issuer_ir","provenance_tier":2,"source_name":"issuer_ir","discovery_source":discovery_source,"issuer_exchange":source.exchange,"exchange":source.exchange,"issuer_type":source.issuer_type,"isin":source.isin,"language":source.language,"source_url":r.url,"document_url":r.url,"attachments":list(r.attachments),"attachment_urls":list(r.attachments),"official_document":True,"officiality":"issuer_published","cross_verified":bool(sgx_id),"canonical_key":canonical,"sgx_announcement_id":sgx_id,"collection_status":"partial","attachments_may_be_missing":not bool(r.attachments),"filing_type":filing_type},market=MARKET_SG,summary=r.summary,effective_at=r.published)


def _sgx_announcement_id(urls: Iterable[str]) -> str:
    for value in urls:
        match = re.match(
            r"^https://links\.sgx\.com/1\.0\.0/corporate-announcements/([A-Z0-9]+)/?$",
            str(value).strip(),
            re.IGNORECASE,
        )
        if match:
            return match.group(1).upper()
    return ""

def load_sources_from_path(path:Path)->tuple[SgIrSource,...]:
    payload=json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload,Mapping) or set(payload)!={"schema","sources"} or payload.get("schema")!=SG_IR_CONFIG_SCHEMA: raise ValueError(f"SG IR config must have schema {SG_IR_CONFIG_SCHEMA} and sources")
    rows=payload.get("sources")
    if not isinstance(rows,list) or not rows: raise ValueError("SG IR sources must be non-empty list")
    allowed={"source_id","ticker","issuer","exchange","feed_url","format","url_rules","filing_terms","page_urls","adapter","issuer_type","isin","language","timezone"}; result=[]
    for row in rows:
        if not isinstance(row,Mapping) or set(row)-allowed or not isinstance(row.get("url_rules"),list): raise ValueError("invalid SG IR source configuration")
        result.append(SgIrSource(source_id=str(row.get("source_id") or ""),ticker=str(row.get("ticker") or ""),issuer=str(row.get("issuer") or ""),exchange=str(row.get("exchange") or ""),feed_url=str(row.get("feed_url") or ""),format=str(row.get("format") or ""),url_rules=tuple(SgIrUrlRule(str(x.get("host") or ""),str(x.get("path_prefix") or "/")) for x in row["url_rules"] if isinstance(x,Mapping)),filing_terms=tuple(row.get("filing_terms") or ()),page_urls=tuple(row.get("page_urls") or ()),adapter=str(row.get("adapter") or "article"),issuer_type=str(row.get("issuer_type") or "ordinary_share"),isin=str(row.get("isin") or ""),language=str(row.get("language") or "en"),timezone=str(row.get("timezone") or "Asia/Singapore")))
    return tuple(result)


def builtin_sg_ir_sources() -> tuple[SgIrSource, ...]:
    """Return audited, key-free issuer sources that work without local config."""
    return (
        SgIrSource(
            source_id="singtel-stock-exchange-announcements",
            ticker="Z74",
            issuer="Singapore Telecommunications Limited",
            exchange="SGX Mainboard",
            feed_url=(
                "https://www.singtel.com/about-us/investor-relations/"
                "stock-exchange-announcements"
            ),
            format="html",
            adapter="singtel_report",
            url_rules=(
                SgIrUrlRule(
                    "www.singtel.com",
                    "/about-us/investor-relations/stock-exchange-announcements",
                ),
                SgIrUrlRule(
                    "cdn1.singteldigital.com",
                    "/content/dam",
                ),
                SgIrUrlRule(
                    "cdn2.singteldigital.com",
                    "/content/dam",
                ),
            ),
            filing_terms=("stockexchange",),
            issuer_type="ordinary_share",
            isin="SG1T75931496",
        ),
        SgIrSource(
            source_id="ocbc-major-regulatory-announcements",
            ticker="O39",
            issuer="Oversea-Chinese Banking Corporation Limited",
            exchange="SGX Mainboard",
            feed_url=(
                "https://www.ocbc.com/group/investors/"
                "regulatory-disclosure.page"
            ),
            format="html",
            adapter="ocbc_regulatory",
            url_rules=(
                SgIrUrlRule(
                    "www.ocbc.com",
                    "/group/investors/regulatory-disclosure.page",
                ),
                SgIrUrlRule("www.ocbc.com", "/iwov-resources"),
                SgIrUrlRule("www.ocbc.com", "/assets/pdf"),
            ),
            filing_terms=("regulatory",),
            issuer_type="ordinary_share",
            isin="SG1S04926220",
        ),
    )
