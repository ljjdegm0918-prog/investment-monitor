"""Parse known public SGX announcement detail links without SGXNET search.

This source never calls the SGX SPA API and never obtains or sends its
runtime authorization token.  Its input is a reviewed list of already-known
``links.sgx.com`` detail URLs discovered through issuer IR or a clearly
labelled third party.  Consequently collection is always partial.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timezone
from html.parser import HTMLParser
import json
import os
from pathlib import Path
import re
import socket
import time
from typing import Any, Callable, Iterable, List, Mapping, Optional, Tuple
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin, urlparse
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

from ...connectors.base import ConnectorUnavailableError
from ...models import CollectionRequest, InformationItem, MARKET_SG
from ...provenance import build_raw_provenance
from ...web_repository import normalize_sg_ticker

CONFIG_SCHEMA = "sgx_known_announcements/v1"
CONFIG_ENV = "SGX_KNOWN_ANNOUNCEMENTS_PATH"
SGX_HOST = "links.sgx.com"
SGT = ZoneInfo("Asia/Singapore")
DETAIL_RE = re.compile(
    r"^/1\.0\.0/corporate-announcements/([A-Z0-9]+)/?$",
    re.IGNORECASE,
)


class SgxAnnouncementRequestError(RuntimeError):
    pass


class SgxAnnouncementDataError(RuntimeError):
    pass


@dataclass(frozen=True)
class SgxAnnouncementDiscovery:
    url: str
    discovery_source: str
    discovery_url: str = ""
    ticker: str = ""

    def __post_init__(self) -> None:
        announcement_id = _announcement_id(self.url)
        source = str(self.discovery_source).strip()
        if not announcement_id or not source:
            raise ValueError("SGX discovery requires a valid detail URL and source")
        if self.discovery_url:
            parsed = urlparse(self.discovery_url)
            if parsed.scheme != "https" or not parsed.hostname:
                raise ValueError("SGX discovery_url must be absolute HTTPS")
        object.__setattr__(self, "url", _detail_url(announcement_id))
        object.__setattr__(self, "discovery_source", source)
        object.__setattr__(self, "ticker", normalize_sg_ticker(self.ticker))


@dataclass(frozen=True)
class ParsedSgxAnnouncement:
    announcement_id: str
    issuer_name: str
    security_name: str
    ticker: str
    isin: str
    title: str
    subtitle: str
    broadcast_at: datetime
    announcement_reference: str
    submitted_by: str
    designation: str
    description: str
    status: str
    attachments: Tuple[Mapping[str, str], ...]
    source_url: str


class SgxAnnouncementConnector:
    name = "sgx_announcements"
    provider = "SGX official known announcement details (partial; no enumeration)"
    source_type = "regulatory_filing"
    source_wide_collection = True
    coverage_kind = "feed_snapshot"
    coverage_level = "official_known_links_partial"

    def __init__(
        self,
        *,
        discoveries: Iterable[SgxAnnouncementDiscovery] = (),
        fetcher: Optional[Callable[[str], str]] = None,
        sleeper: Callable[[float], None] = time.sleep,
        retry_attempts: int = 3,
    ) -> None:
        self._discoveries = tuple(discoveries)
        if len({item.url for item in self._discoveries}) != len(self._discoveries):
            raise ValueError("SGX known-link config contains duplicate URLs")
        self._fetcher = fetcher or _fetch_html
        self._sleeper = sleeper
        self._retry_attempts = max(1, int(retry_attempts))
        self._last_errors: Tuple[Tuple[str, str], ...] = ()
        self.last_failure_details: Tuple[Mapping[str, str], ...] = ()
        self.last_collection_status = "empty"
        self.last_records_read = 0

    @classmethod
    def configuration_error(cls) -> Optional[str]:
        raw_path = os.environ.get(CONFIG_ENV, "").strip()
        if not raw_path:
            return f"{CONFIG_ENV} is not configured."
        try:
            load_discoveries(Path(raw_path))
        except (OSError, ValueError, json.JSONDecodeError) as error:
            return f"SGX known-announcement config is invalid: {error}"
        return None

    @classmethod
    def from_environment(cls) -> "SgxAnnouncementConnector":
        error = cls.configuration_error()
        if error:
            raise ConnectorUnavailableError(error)
        return cls(discoveries=load_discoveries(Path(os.environ[CONFIG_ENV])))

    @property
    def last_errors(self) -> Tuple[Tuple[str, str], ...]:
        return self._last_errors

    def collect(self, request: CollectionRequest) -> List[InformationItem]:
        wanted = {
            normalize_sg_ticker(ticker) for ticker in request.tickers
            if request.market_for(ticker) == MARKET_SG
            or request.market_for(normalize_sg_ticker(ticker)) == MARKET_SG
        }
        if not wanted:
            self._set_status("empty", (), 0)
            return []
        items: List[InformationItem] = []
        errors: List[Tuple[str, str]] = []
        read = 0
        collected_at = datetime.now(timezone.utc)
        for index, discovery in enumerate(self._discoveries):
            if discovery.ticker and discovery.ticker not in wanted:
                continue
            if index:
                self._sleeper(0.25)
            try:
                parsed = parse_sgx_announcement_detail(
                    self._retry_fetch(discovery.url), source_url=discovery.url
                )
                read += 1
                ticker = normalize_sg_ticker(parsed.ticker or discovery.ticker)
                if not ticker or ticker not in wanted:
                    continue
                local_day = parsed.broadcast_at.astimezone(SGT).date()
                if not request.start_date <= local_day <= request.end_date:
                    continue
                items.append(_to_item(parsed, discovery, collected_at))
            except Exception as error:
                message = str(error) or error.__class__.__name__
                errors.append((discovery.ticker or "*", message))
        if errors:
            status = "partial" if items else "unavailable"
        else:
            # A reviewed list can prove only what it contains, never that a
            # date range has no SGXNET announcements.
            status = "partial" if items else "unavailable"
        self._set_status(status, errors, read)
        return items

    def _retry_fetch(self, url: str) -> str:
        for attempt in range(self._retry_attempts):
            try:
                return self._fetcher(url)
            except SgxAnnouncementRequestError as error:
                blocked = any(code in str(error) for code in ("HTTP 403", "HTTP 429"))
                if blocked or attempt + 1 >= self._retry_attempts:
                    raise
                self._sleeper(min(2 ** attempt, 4))
        raise SgxAnnouncementRequestError("SGX retry loop ended unexpectedly")

    def _set_status(
        self, status: str, errors: Iterable[Tuple[str, str]], read: int
    ) -> None:
        self.last_collection_status = status
        self._last_errors = tuple(errors)
        self.last_records_read = read
        self.last_failure_details = tuple({
            "feed": "SGX known announcement detail",
            "url": "",
            "message": f"{ticker}: {message}",
        } for ticker, message in self._last_errors)


def parse_sgx_announcement_detail(
    html: str, *, source_url: str
) -> ParsedSgxAnnouncement:
    announcement_id = _announcement_id(source_url)
    if not announcement_id:
        raise SgxAnnouncementDataError("SGX detail URL is invalid")
    parser = _SgxHtmlParser()
    parser.feed(str(html))
    parser.close()
    text = "\n".join(line for line in parser.lines if line)
    lowered = text.casefold()
    if not text or "loading" == lowered.strip() or "access denied" in lowered:
        raise SgxAnnouncementDataError("SGX detail returned loading/access page")
    labels = (
        "Issuer/ Manager", "Securities", "Security", "Announcement Title",
        "Announcement Sub Title", "Date & Time of Broadcast",
        "Date &Time of Broadcast", "Status", "Announcement Reference",
        "Submitted By (Co./ Ind. Name)", "Submitted By", "Designation", "Description",
        "Attachments", "Related Announcements",
    )
    values = {label: _label_value(text, label, labels) for label in labels}
    issuer = values["Issuer/ Manager"]
    security = values["Securities"] or values["Security"]
    title = values["Announcement Title"]
    broadcast_raw = (
        values["Date & Time of Broadcast"]
        or values["Date &Time of Broadcast"]
    )
    reference = values["Announcement Reference"]
    if not all((issuer, security, title, broadcast_raw, reference)):
        raise SgxAnnouncementDataError("SGX detail is missing required official fields")
    broadcast = _parse_broadcast(broadcast_raw)
    security_name, isin, ticker = _security_identity(security)
    attachments: List[Mapping[str, str]] = []
    prefix = f"/1.0.0/corporate-announcements/{announcement_id}/".lower()
    for link in parser.links:
        resolved = urljoin(source_url, link["href"])
        parsed = urlparse(resolved)
        if parsed.scheme != "https" or (parsed.hostname or "").lower() != SGX_HOST:
            continue
        if not (
            parsed.path.lower().startswith(prefix)
            or parsed.path.lower().startswith("/fileopen/")
        ):
            continue
        name = link["text"] or parsed.path.rsplit("/", 1)[-1]
        size_match = re.search(r"\b([\d.]+\s*(?:KB|MB|GB))\b", name, re.I)
        attachments.append({
            "name": re.sub(r"\s*\(?[\d.]+\s*(?:KB|MB|GB)\)?\s*$", "", name, flags=re.I),
            "url": resolved,
            "size": size_match.group(1) if size_match else "",
        })
    if not attachments and "attachment" in lowered:
        raise SgxAnnouncementDataError("SGX detail declared attachments but none parsed")
    return ParsedSgxAnnouncement(
        announcement_id=announcement_id,
        issuer_name=issuer,
        security_name=security_name,
        ticker=ticker,
        isin=isin,
        title=title,
        subtitle=values["Announcement Sub Title"],
        broadcast_at=broadcast,
        announcement_reference=reference,
        submitted_by=(
            values["Submitted By (Co./ Ind. Name)"] or values["Submitted By"]
        ),
        designation=values["Designation"],
        description=values["Description"],
        status=values["Status"],
        attachments=tuple(attachments),
        source_url=_detail_url(announcement_id),
    )


class _SgxHtmlParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.lines: List[str] = []
        self.links: List[Mapping[str, str]] = []
        self._parts: List[str] = []
        self._href: Optional[str] = None
        self._link_parts: List[str] = []

    def handle_starttag(self, tag: str, attrs: List[Tuple[str, Optional[str]]]) -> None:
        values = {key: value or "" for key, value in attrs}
        if tag == "a" and values.get("href"):
            self._href = values["href"]
            self._link_parts = []
        if tag in {"br", "hr"}:
            self._flush()

    def handle_data(self, data: str) -> None:
        self._parts.append(data)
        if self._href is not None:
            self._link_parts.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag == "a" and self._href is not None:
            self.links.append({
                "href": self._href,
                "text": " ".join("".join(self._link_parts).split()),
            })
            self._href = None
            self._link_parts = []
        if tag in {"div", "p", "td", "th", "li", "section", "h1", "h2", "h3"}:
            self._flush()

    def close(self) -> None:
        super().close()
        self._flush()

    def _flush(self) -> None:
        value = " ".join("".join(self._parts).split())
        if value:
            self.lines.append(value)
        self._parts = []


def _to_item(
    parsed: ParsedSgxAnnouncement,
    discovery: SgxAnnouncementDiscovery,
    collected_at: datetime,
) -> InformationItem:
    filing_type = _classify(parsed.title, parsed.subtitle)
    attachment_urls = [item["url"] for item in parsed.attachments]
    # The opaque permalink id is also visible in issuer IR links, making it
    # the strongest identity that can be shared before the detail is parsed.
    canonical_key = f"sgx-id:{parsed.announcement_id}"
    metadata = {
        **build_raw_provenance(
            official_source_id=parsed.announcement_reference,
            official_source_url=parsed.source_url,
            retrieval_url=parsed.source_url,
            raw_payload={
                "announcement_id": parsed.announcement_id,
                "reference": parsed.announcement_reference,
                "issuer": parsed.issuer_name,
                "security": parsed.security_name,
                "attachments": list(parsed.attachments),
            },
            raw_payload_format="html_parsed_record",
            classification_code=filing_type,
            classification_label=filing_type,
            published_at_raw=parsed.broadcast_at.isoformat(),
            published_timezone="Asia/Singapore",
            revision_semantics=_revision_semantics(parsed),
        ),
        "source_tier": 1,
        "source_tier_label": "sgx_official",
        "source_name": "sgx",
        "exchange": "SGX",
        "language": "en",
        "source_url": parsed.source_url,
        "document_url": parsed.source_url,
        "official_document": True,
        "is_official": True,
        "canonical_key": canonical_key,
        "announcement_id": parsed.announcement_id,
        "announcement_reference": parsed.announcement_reference,
        "security_name": parsed.security_name,
        "isin": parsed.isin,
        "subtitle": parsed.subtitle,
        "submitted_by": parsed.submitted_by,
        "designation": parsed.designation,
        "description": parsed.description,
        "status": parsed.status,
        "filing_type": filing_type,
        "attachments": list(parsed.attachments),
        "attachment_urls": attachment_urls,
        "discovery_source": discovery.discovery_source,
        "discovery_url": discovery.discovery_url,
        "cross_verified": discovery.discovery_source not in {"manual", "unknown"},
        "collection_status": "partial",
    }
    return InformationItem(
        source="sgx_announcements",
        source_type="regulatory_filing",
        external_id=f"sgx:{parsed.announcement_id}",
        tickers=(normalize_sg_ticker(parsed.ticker or discovery.ticker),),
        issuer=parsed.issuer_name,
        published_at=parsed.broadcast_at,
        title=parsed.title,
        document_type=filing_type,
        url=parsed.source_url,
        collected_at=collected_at,
        raw_metadata=metadata,
        market=MARKET_SG,
        summary=parsed.description or parsed.subtitle or None,
        effective_at=parsed.broadcast_at,
    )


def load_discoveries(path: Path) -> Tuple[SgxAnnouncementDiscovery, ...]:
    with path.open("r", encoding="utf-8") as handle:
        payload = json.load(handle)
    if not isinstance(payload, Mapping) or set(payload) != {"schema", "announcements"}:
        raise ValueError("SGX config must contain only schema and announcements")
    if payload.get("schema") != CONFIG_SCHEMA:
        raise ValueError(f"SGX config schema must be {CONFIG_SCHEMA}")
    rows = payload.get("announcements")
    if not isinstance(rows, list) or not rows:
        raise ValueError("SGX announcements must be a non-empty list")
    result = []
    for row in rows:
        if not isinstance(row, Mapping) or set(row) - {
            "url", "discovery_source", "discovery_url", "ticker"
        }:
            raise ValueError("SGX discovery row is invalid")
        result.append(SgxAnnouncementDiscovery(
            url=str(row.get("url") or ""),
            discovery_source=str(row.get("discovery_source") or ""),
            discovery_url=str(row.get("discovery_url") or ""),
            ticker=str(row.get("ticker") or ""),
        ))
    return tuple(result)


def _fetch_html(url: str) -> str:
    request = Request(url, headers={
        "User-Agent": "InvestmentMonitor/sgx-known-links",
        "Accept": "text/html,application/xhtml+xml",
    })
    # No authorization header, cookie fabrication, or token replay.
    try:
        with urlopen(request, timeout=20) as response:  # nosec B310 validated URL
            return str(response.read().decode(
                response.headers.get_content_charset() or "utf-8", errors="strict"
            ))
    except HTTPError as error:
        raise SgxAnnouncementRequestError(f"HTTP {error.code}") from error
    except (URLError, TimeoutError, socket.timeout, OSError) as error:
        raise SgxAnnouncementRequestError(str(error) or error.__class__.__name__) from error


def _announcement_id(url: str) -> str:
    parsed = urlparse(str(url).strip())
    if parsed.scheme != "https" or (parsed.hostname or "").lower() != SGX_HOST:
        return ""
    match = DETAIL_RE.fullmatch(parsed.path)
    return match.group(1).upper() if match else ""


def _detail_url(announcement_id: str) -> str:
    return f"https://{SGX_HOST}/1.0.0/corporate-announcements/{announcement_id}/"


def _label_value(text: str, label: str, labels: Iterable[str]) -> str:
    lowered = text.casefold()
    marker = label.casefold()
    start = lowered.find(marker)
    if start < 0:
        return ""
    start += len(label)
    while start < len(text) and text[start] in " \t:\r\n":
        start += 1
    ends = [
        lowered.find(other.casefold(), start) for other in labels
        if other != label and lowered.find(other.casefold(), start) >= 0
    ]
    end = min(ends) if ends else len(text)
    return " ".join(text[start:end].split()).strip(" :-")


def _security_identity(value: str) -> Tuple[str, str, str]:
    isin_match = re.search(r"\b([A-Z]{2}[A-Z0-9]{9}[0-9])\b", value, re.I)
    if not isin_match:
        raise SgxAnnouncementDataError("SGX Securities field has no ISIN")
    isin = isin_match.group(1).upper()
    before = value[:isin_match.start()].strip(" -")
    after = value[isin_match.end():].strip(" -")
    ticker_match = re.search(r"\b([A-Z0-9]{1,8})\b", after, re.I)
    if not ticker_match:
        raise SgxAnnouncementDataError("SGX Securities field has no ticker")
    return before, isin, normalize_sg_ticker(ticker_match.group(1))


def _parse_broadcast(value: str) -> datetime:
    cleaned = re.sub(r"\b(?:SGT|Singapore Time)\b", "", value, flags=re.I).strip()
    for fmt in (
        "%d %b %Y %H:%M:%S", "%d %b %Y %H:%M", "%d/%m/%Y %H:%M:%S",
        "%d-%b-%Y %H:%M:%S", "%Y-%m-%d %H:%M:%S",
    ):
        try:
            return datetime.strptime(cleaned, fmt).replace(tzinfo=SGT)
        except ValueError:
            continue
    raise SgxAnnouncementDataError("SGX broadcast timestamp is unparseable")


def _classify(title: str, subtitle: str) -> str:
    text = f"{title} {subtitle}".casefold()
    rules = (
        ("sustainability_report", ("sustainability report",)),
        ("annual_report", ("annual report",)),
        ("financial_results", ("financial results", "results announcement", "earnings")),
        ("acquisition_disposal", ("acquisition", "disposal", "divestment", "merger")),
        ("share_buyback", ("share buyback", "share purchase mandate", "repurchase")),
        ("dividend", ("dividend", "distribution")),
        ("management_change", ("appointment", "resignation", "cessation", "director")),
        ("trading_resumption", ("trading resumption", "resume trading", "reinstatement")),
        ("trading_halt", ("trading halt", "suspension")),
        ("general_meeting", ("annual general meeting", "extraordinary general meeting", "agm", "egm")),
        ("circular", ("circular",)),
        ("offer_document", ("offer document",)),
        ("prospectus", ("prospectus",)),
        ("capital_change", ("capital change", "issue of shares", "share capital")),
        ("financing", ("financing", "placement", "rights issue", "notes issue")),
        ("material_information", ("material information", "material update", "contract")),
    )
    for filing_type, terms in rules:
        if any(term in text for term in terms):
            return filing_type
    return "other_filing"


def _revision_semantics(parsed: ParsedSgxAnnouncement) -> str:
    text = f"{parsed.title} {parsed.subtitle} {parsed.status}".casefold()
    if "withdraw" in text:
        return "withdrawal"
    if "replace" in text:
        return "replacement"
    if "correct" in text or "amend" in text:
        return "correction"
    return "original"
