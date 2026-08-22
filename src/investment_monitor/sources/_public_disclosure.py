"""Shared machinery for key-free public exchange disclosure feeds."""

from __future__ import annotations

import html
import json
import re
import time
from datetime import date, datetime, timezone
from hashlib import sha256
from typing import Any, Callable, Iterable, List, Mapping, Optional, Sequence, Tuple
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from ..models import CollectionRequest, InformationItem
from ..provenance import build_raw_provenance


class PublicDisclosureError(RuntimeError):
    """A public disclosure endpoint could not be read or parsed."""


def fetch_text(
    url: str,
    *,
    data: Optional[bytes] = None,
    headers: Optional[Mapping[str, str]] = None,
    timeout: int = 30,
    max_attempts: int = 3,
    sleeper: Callable[[float], None] = time.sleep,
) -> Tuple[str, Mapping[str, str]]:
    request_headers = {
        "Accept": "text/html,application/json;q=0.9,*/*;q=0.8",
        # Several exchange CDNs reject non-browser UAs even for their documented
        # public pages/APIs. Keep a stable, ordinary UA and identify provenance
        # in stored metadata instead.
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0 Safari/537.36"
        ),
        **dict(headers or {}),
    }
    attempts = max(1, max_attempts)
    last_error: Optional[BaseException] = None
    for attempt in range(attempts):
        request = Request(url, data=data, headers=request_headers)
        try:
            with urlopen(request, timeout=timeout) as response:
                payload = response.read().decode("utf-8", errors="replace")
                return payload, dict(response.headers.items())
        except HTTPError as error:
            last_error = error
            detail = error.read().decode("utf-8", errors="replace")[:500]
            retryable = error.code in {408, 425, 429} or 500 <= error.code < 600
            if not retryable or attempt + 1 >= attempts:
                raise PublicDisclosureError(
                    f"{url}: HTTP {error.code}: {detail or error.reason}"
                ) from error
            retry_after = error.headers.get("Retry-After") if error.headers else None
            try:
                if retry_after is None:
                    raise ValueError("no Retry-After")
                delay = min(30.0, max(0.0, float(retry_after)))
            except (TypeError, ValueError):
                delay = min(4.0, 0.5 * (2**attempt))
            sleeper(delay)
        except (URLError, TimeoutError, OSError) as error:
            last_error = error
            if attempt + 1 >= attempts:
                raise PublicDisclosureError(f"{url}: {error}") from error
            sleeper(min(4.0, 0.5 * (2**attempt)))
    raise PublicDisclosureError(f"{url}: {last_error}")


def fetch_json(
    url: str,
    *,
    payload: Optional[Mapping[str, Any]] = None,
    headers: Optional[Mapping[str, str]] = None,
) -> Tuple[Any, Mapping[str, str]]:
    data = None
    request_headers = dict(headers or {})
    if payload is not None:
        data = json.dumps(payload, separators=(",", ":")).encode("utf-8")
        request_headers["Content-Type"] = "application/json"
    text, response_headers = fetch_text(
        url, data=data, headers=request_headers
    )
    try:
        return json.loads(text), response_headers
    except json.JSONDecodeError as error:
        raise PublicDisclosureError(f"{url}: invalid JSON") from error


def clean_html(value: str) -> str:
    return " ".join(
        html.unescape(re.sub(r"<[^>]+>", " ", value or "")).split()
    )


def stable_id(prefix: str, value: str) -> str:
    return f"{prefix}:{sha256(value.encode('utf-8')).hexdigest()[:24]}"


def company_key(value: str) -> str:
    value = html.unescape(str(value or "")).casefold()
    value = re.sub(
        r"\b(ag|sa|s\.a\.?|plc|ltd|limited|nv|asa|as|nyrt|rt|kft|inc|corp|corporation|company)\b",
        " ",
        value,
    )
    return " ".join(re.findall(r"\w+", value, flags=re.UNICODE))


def record_matches(
    record: Mapping[str, Any],
    ticker: str,
    identity: Mapping[str, str],
    normalizer: Callable[[str], str],
) -> bool:
    official_ticker = str(record.get("ticker") or "").strip()
    if official_ticker and normalizer(official_ticker) == ticker:
        return True
    haystack = company_key(
        f"{record.get('issuer') or ''} {record.get('title') or ''}"
    )
    ticker_key = company_key(ticker)
    if ticker_key and re.search(rf"(?:^|\s){re.escape(ticker_key)}(?:\s|$)", haystack):
        return True
    name = company_key(str(identity.get("name") or ""))
    return bool(name and len(name) >= 4 and (name in haystack or haystack in name))


class PublicDisclosureConnector:
    """Map a source-wide official feed to requested market tickers."""

    name = "public_disclosure"
    provider = "Public disclosure source"
    max_lookback_days = 30
    source_type = "regulatory_filing"
    coverage_level = "official"
    preserve_unmatched_records = False

    def __init__(
        self,
        *,
        client: Any,
        universe: Mapping[str, Mapping[str, str]],
        normalizer: Callable[[str], str],
        market: str,
    ) -> None:
        self._client = client
        self._universe = dict(universe)
        self._normalizer = normalizer
        self._market = market
        self._last_errors: Tuple[Tuple[str, str], ...] = ()
        self.last_collection_status = "empty"
        self.last_records_read = 0
        self.last_unmatched_records = 0

    @property
    def last_errors(self) -> Tuple[Tuple[str, str], ...]:
        return self._last_errors

    def collect(self, request: CollectionRequest) -> List[InformationItem]:
        tickers = tuple(
            dict.fromkeys(
                self._normalizer(ticker)
                for ticker in request.tickers
                if request.market_for(ticker) == self._market
            )
        )
        if not tickers:
            self._last_errors = ()
            self.last_collection_status = "empty"
            self.last_records_read = 0
            self.last_unmatched_records = 0
            return []
        try:
            fetch_for_tickers = getattr(self._client, "fetch_for_tickers", None)
            if callable(fetch_for_tickers):
                records = list(fetch_for_tickers(tickers, request.start_date, request.end_date))
            else:
                records = list(self._client.fetch(request.start_date, request.end_date))
        except Exception as error:
            message = str(error) or error.__class__.__name__
            self._last_errors = (("*", message),)
            self.last_collection_status = "failure"
            self.last_records_read = 0
            self.last_unmatched_records = 0
            raise PublicDisclosureError(message) from error

        client_errors = tuple(getattr(self._client, "last_ticker_errors", ()) or ())

        self.last_records_read = len(records)
        collected_at = datetime.now(timezone.utc)
        items: List[InformationItem] = []
        seen = set()
        unmatched_records = 0
        for record in records:
            published_at = record.get("published_at")
            if not isinstance(published_at, datetime):
                continue
            local_day = published_at.astimezone(
                getattr(self._client, "timezone", timezone.utc)
            ).date()
            if not request.start_date <= local_day <= request.end_date:
                continue
            matched = tuple(
                ticker
                for ticker in tickers
                if record_matches(
                    record,
                    ticker,
                    self._universe.get(ticker, {}),
                    self._normalizer,
                )
            )
            if not matched:
                if not self.preserve_unmatched_records:
                    continue
                unmatched_records += 1
            external_id = str(record.get("external_id") or "").strip()
            if not external_id:
                external_id = stable_id(self.name, str(record.get("url") or record))
            dedupe = (external_id, matched)
            if dedupe in seen:
                continue
            seen.add(dedupe)
            source_url = str(record.get("url") or "")
            raw = record.get("raw_payload") or dict(record)
            issuer = str(record.get("issuer") or (matched[0] if matched else "Unmatched issuer"))
            items.append(InformationItem(
                source=self.name,
                source_type=self.source_type,
                external_id=external_id,
                tickers=matched,
                issuer=issuer,
                published_at=published_at,
                title=str(record.get("title") or "Untitled disclosure"),
                document_type=str(record.get("document_type") or "announcement"),
                url=source_url,
                collected_at=collected_at,
                raw_metadata={
                    **build_raw_provenance(
                        official_source_id=external_id,
                        official_source_url=source_url,
                        retrieval_url=str(record.get("retrieval_url") or ""),
                        raw_payload=raw,
                        raw_payload_format=str(record.get("raw_payload_format") or "html"),
                        classification_code=str(record.get("classification_code") or "") or None,
                        classification_label=str(record.get("document_type") or "") or None,
                        published_at_raw=str(record.get("published_at_raw") or "") or None,
                        published_timezone=str(record.get("published_timezone") or "unknown"),
                        revision_semantics=str(record.get("revision_semantics") or "unknown"),
                    ),
                    "provider": self.provider,
                    "coverage_level": self.coverage_level,
                    "attachments": list(record.get("attachments") or []),
                    "match_status": "matched" if matched else "pending",
                    "identity_candidates": {
                        "ticker": str(record.get("ticker") or "") or None,
                        "isin": str(record.get("isin") or "") or None,
                        "lei": str(record.get("lei") or "") or None,
                        "issuer": str(record.get("issuer") or "") or None,
                    },
                },
                market=self._market,
                summary=str(record.get("summary") or "") or None,
                effective_at=published_at,
            ))
        self._last_errors = client_errors
        self.last_unmatched_records = unmatched_records
        if client_errors:
            self.last_collection_status = "success" if items else "failure"
        else:
            self.last_collection_status = "success" if items else "empty"
        return items


def paged_urls(
    build_url: Callable[[int], str],
    parse_page: Callable[[str, str], Sequence[Mapping[str, Any]]],
    start_date: date,
    *,
    max_pages: int = 200,
) -> Iterable[Mapping[str, Any]]:
    """Read descending HTML pages until exhausted or older than start_date."""
    seen_ids: set[str] = set()
    for page in range(1, max_pages + 1):
        url = build_url(page)
        text, _ = fetch_text(url)
        records = list(parse_page(text, url))
        if not records:
            return
        page_ids = [
            str(record.get("external_id") or record.get("url") or record)
            for record in records
        ]
        if len(set(page_ids)) != len(page_ids) or set(page_ids) & seen_ids:
            raise PublicDisclosureError(
                f"pagination repeated or overlapped records on page {page}"
            )
        oldest: Optional[date] = None
        for record, identifier in zip(records, page_ids):
            seen_ids.add(identifier)
            published = record.get("published_at")
            if isinstance(published, datetime):
                day = published.date()
                oldest = day if oldest is None else min(oldest, day)
            yield record
        if oldest is not None and oldest < start_date:
            return
    raise PublicDisclosureError(
        f"pagination reached max_pages={max_pages} before a terminal page"
    )
