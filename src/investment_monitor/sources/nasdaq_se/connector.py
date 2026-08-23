"""Official Nasdaq Nordic company announcements for Swedish listings."""

from __future__ import annotations

import re
from difflib import SequenceMatcher
from datetime import datetime, timezone
from typing import Any, List, Mapping, Sequence, Tuple
from zoneinfo import ZoneInfo

from ...models import CollectionRequest, InformationItem, MARKET_SE
from ...provenance import build_raw_provenance
from .client import NasdaqSeClient, NasdaqSeRequestError

STOCKHOLM = ZoneInfo("Europe/Stockholm")
MARKETS = (
    ("NordicMainMarkets", "Main Market, Stockholm"),
    ("NordicFirstNorth", "First North Sweden"),
)


class NasdaqSeFilingsConnector:
    name = "nasdaq_se_filings"
    provider = "Nasdaq Nordic Company News (official)"
    max_lookback_days = 365

    def __init__(self, client: NasdaqSeClient | None = None) -> None:
        self._client = client or NasdaqSeClient.from_environment()
        self._last_errors: Tuple[Tuple[str, str], ...] = ()

    @property
    def last_errors(self) -> Tuple[Tuple[str, str], ...]:
        return self._last_errors

    def collect(self, request: CollectionRequest) -> List[InformationItem]:
        items: List[InformationItem] = []
        failures: List[Tuple[str, str]] = []
        try:
            directory = self._client.fetch_share_directory()
        except Exception as error:
            message = str(error) or error.__class__.__name__
            self._last_errors = tuple((ticker, message) for ticker in request.tickers)
            if len(request.tickers) == 1:
                raise NasdaqSeRequestError(message) from error
            return []
        for ticker in request.tickers:
            if request.market_for(ticker) != MARKET_SE:
                continue
            try:
                share_identity = _share_identity_for_ticker(directory, ticker)
                if not share_identity:
                    raise NasdaqSeRequestError("no_official_share_identity")
                display_name, listing_category = share_identity
                records: List[Mapping[str, Any]] = []
                global_name, market = (
                    MARKETS[0] if listing_category == "MAIN_MARKET" else MARKETS[1]
                )
                company_names = self._client.fetch_company_names(global_name, market)
                company = _resolve_company_name(display_name, company_names)
                if not company:
                    raise NasdaqSeRequestError("no_official_announcement_identity")
                records.extend(
                    self._client.fetch_announcements(
                        company,
                        request.start_date,
                        request.end_date,
                        global_name=global_name,
                        market=market,
                    )
                )
                items.extend(_map_records(records, ticker))
            except Exception as error:
                failures.append((ticker, str(error) or error.__class__.__name__))
        self._last_errors = tuple(failures)
        if len(request.tickers) == 1 and failures:
            raise NasdaqSeRequestError(failures[0][1])
        return items


def _share_identity_for_ticker(
    rows: Sequence[Mapping[str, Any]], ticker: str
) -> tuple[str, str] | None:
    wanted = _normalize_symbol(ticker)
    matches = [
        row
        for row in rows
        if _normalize_symbol(str(row.get("symbol") or "")) == wanted
    ]
    if len(matches) != 1:
        return None
    name = str(matches[0].get("fullName") or "").strip()
    category = str(matches[0].get("listing_category") or "")
    if not name or category not in {"MAIN_MARKET", "FIRST_NORTH"}:
        return None
    return name, category


def _resolve_company_name(display_name: str, candidates: Sequence[str]) -> str | None:
    base = _normalize_company(display_name)
    ranked = sorted(
        ((SequenceMatcher(None, base, _normalize_company(candidate)).ratio(), candidate) for candidate in candidates),
        reverse=True,
    )
    if not ranked or ranked[0][0] < 0.72:
        return None
    if len(ranked) > 1 and ranked[0][0] - ranked[1][0] < 0.04:
        return None
    return ranked[0][1]


def _normalize_symbol(value: str) -> str:
    value = re.sub(r"\.(ST|SE)$", "", value.strip().upper())
    return re.sub(r"[-_.\s]+", " ", value).strip()


def _normalize_company(value: str) -> str:
    words = re.findall(r"[0-9a-zåäö]+", value.casefold())
    if words and words[-1] in {"a", "b"}:
        words.pop()
    ignored = {"ab", "publ", "aktiebolag", "telefonab", "l", "m"}
    return " ".join(word for word in words if word not in ignored)


def _map_records(records: Sequence[Mapping[str, Any]], ticker: str) -> List[InformationItem]:
    collected_at = datetime.now(timezone.utc)
    seen = set()
    items: List[InformationItem] = []
    for record in records:
        external_id = str(record.get("disclosureId") or "")
        language = str(record.get("language") or "")
        identity = (external_id, language)
        if not external_id or identity in seen:
            continue
        seen.add(identity)
        published_raw = str(record.get("published") or record.get("releaseTime") or "")
        published = datetime.strptime(published_raw, "%Y-%m-%d %H:%M:%S").replace(tzinfo=STOCKHOLM)
        url = str(record.get("messageUrl") or "")
        items.append(
            InformationItem(
                source="nasdaq_se_filings",
                source_type="regulatory_filing",
                external_id=f"{external_id}:{language or 'und'}",
                tickers=(ticker,),
                issuer=str(record.get("company") or ticker),
                published_at=published,
                title=str(record.get("headline") or ""),
                document_type=str(record.get("cnsCategory") or "company_announcement"),
                url=url,
                collected_at=collected_at,
                raw_metadata={
                    **build_raw_provenance(
                        official_source_id=external_id,
                        official_source_url=url,
                        retrieval_url=str(record.get("retrieval_url") or ""),
                        raw_payload=record,
                        raw_payload_format="json",
                        classification_code=str(record.get("categoryId") or "") or None,
                        classification_label=str(record.get("cnsCategory") or "") or None,
                        published_at_raw=published_raw,
                        published_timezone="Europe/Stockholm",
                    ),
                    "language": language,
                    "market_name": str(record.get("market") or ""),
                    "attachments": record.get("attachment") or [],
                },
                market=MARKET_SE,
                effective_at=published,
            )
        )
    return items
