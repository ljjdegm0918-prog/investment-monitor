"""Canadian SEDAR filing mirror via CEO.ca's public SEDAR bot channel.

CEO.ca is not the regulator and its undocumented endpoint cannot prove a
gapless SEDAR+ history.  This connector is therefore deliberately ``partial``
and records third-party mirror provenance on every item.
"""

from __future__ import annotations

import json
from datetime import date, datetime, timezone
from typing import Any, Callable, List, Mapping, Optional, Tuple
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

from ...models import MARKET_CA, CollectionRequest, InformationItem
from ...web_repository import normalize_ca_ticker
from ..ca_ir.connector import classify_ca_filing
from .parser import CeocaSedarRow, parse_ceoca_sedar_spiels

API_BASE = "https://new-api.ceo.ca/api/get_spiels"
DEFAULT_USER_AGENT = "Mozilla/5.0 (compatible; InvestmentMonitor/0.1)"
PAGE_SIZE = 50
MAX_PAGES_PER_TICKER = 20
MAX_DATE_RANGE_DAYS = 31
TORONTO = ZoneInfo("America/Toronto")


class CeocaSedarRequestError(RuntimeError):
    """Raised when the SEDAR mirror cannot be read safely."""


class CeocaSedarConnector:
    name = "ceoca_sedar"
    provider = "CEO.ca SEDAR mirror"
    status = "partial"
    coverage_kind = "feed_snapshot"
    max_lookback_days = MAX_DATE_RANGE_DAYS

    def __init__(
        self,
        *,
        user_agent: str = DEFAULT_USER_AGENT,
        fetch_json: Optional[
            Callable[[str, str, Optional[int]], Mapping[str, Any]]
        ] = None,
    ) -> None:
        self._user_agent = user_agent
        self._fetch_json = fetch_json or self._fetch_page
        self._last_errors: Tuple[Tuple[str, str], ...] = ()
        self.last_collection_status = "partial"
        self.last_failure_details: Tuple[Mapping[str, str], ...] = ()

    @property
    def last_errors(self) -> Tuple[Tuple[str, str], ...]:
        return self._last_errors

    def collect(self, request: CollectionRequest) -> List[InformationItem]:
        wanted = {
            normalize_ca_ticker(ticker)
            for ticker in request.tickers
            if request.market_for(normalize_ca_ticker(ticker)) == MARKET_CA
        }
        if not wanted:
            self._last_errors = ()
            self.last_collection_status = "empty"
            self.last_failure_details = ()
            return []
        collected_at = datetime.now(timezone.utc)
        items: List[InformationItem] = []
        failures: List[Tuple[str, str]] = []
        for ticker in sorted(wanted):
            try:
                rows = self._fetch_range(
                    ticker.lower(), request.start_date, request.end_date
                )
                items.extend(
                    self._map_row(row, collected_at)
                    for row in rows
                    if normalize_ca_ticker(row.ticker) == ticker
                )
            except Exception as error:
                failures.append((ticker, str(error) or error.__class__.__name__))
        self._last_errors = tuple(failures)
        self.last_failure_details = tuple(
            {
                "feed": "CEO.ca SEDAR mirror",
                "url": API_BASE,
                "message": f"{ticker}: {message}",
            }
            for ticker, message in failures
        )
        if len(wanted) == 1 and failures:
            self.last_collection_status = "unavailable"
            raise CeocaSedarRequestError(failures[0][1])
        if failures:
            # Preserve verified issuers while making the incomplete scope
            # explicit to the pipeline. A failed issuer must never turn a
            # successful subset into a claim of complete Canadian coverage.
            self.last_collection_status = "partial"
            return items
        # CEO.ca is a rolling third-party mirror. Even a clean request cannot
        # prove SEDAR+ completeness, so it is intentionally never "success".
        self.last_collection_status = "partial" if items else "empty"
        return items

    def _fetch_range(
        self, channel: str, start_date: date, end_date: date
    ) -> List[CeocaSedarRow]:
        if (end_date - start_date).days + 1 > MAX_DATE_RANGE_DAYS:
            raise CeocaSedarRequestError(
                f"CEO.ca SEDAR range exceeds {MAX_DATE_RANGE_DAYS} days"
            )
        collected: List[CeocaSedarRow] = []
        until: Optional[int] = None
        covered_start = False
        for _ in range(MAX_PAGES_PER_TICKER):
            payload = self._fetch_json(channel, self._user_agent, until)
            spiels = payload.get("spiels")
            if not isinstance(spiels, list):
                raise CeocaSedarRequestError("CEO.ca SEDAR response has no spiels list")
            if not spiels:
                covered_start = True
                break
            timestamps = []
            for entry in spiels:
                if not isinstance(entry, Mapping):
                    raise CeocaSedarRequestError("CEO.ca SEDAR spiel is not an object")
                try:
                    raw_timestamp = entry.get("timestamp")
                    if raw_timestamp is None:
                        continue
                    timestamps.append(int(raw_timestamp))
                except (TypeError, ValueError):
                    continue
            if not timestamps:
                raise CeocaSedarRequestError("CEO.ca SEDAR page has no valid timestamp")
            collected.extend(
                parse_ceoca_sedar_spiels(
                    spiels,
                    start_date=start_date,
                    end_date=end_date,
                    expected_channel=channel,
                )
            )
            oldest_ms = min(timestamps)
            oldest_day = datetime.fromtimestamp(
                oldest_ms / 1000.0, tz=timezone.utc
            ).astimezone(TORONTO).date()
            if oldest_day < start_date or len(spiels) < PAGE_SIZE:
                covered_start = True
                break
            next_until = oldest_ms - 1
            if until is not None and next_until >= until:
                raise CeocaSedarRequestError("CEO.ca SEDAR pagination did not advance")
            until = next_until
        if not covered_start:
            raise CeocaSedarRequestError(
                f"CEO.ca SEDAR pagination cap reached for {channel!r}; "
                "refusing incomplete results"
            )
        return list({row.spiel_id: row for row in collected}.values())

    def _map_row(self, row: CeocaSedarRow, collected_at: datetime) -> InformationItem:
        ticker = normalize_ca_ticker(row.ticker)
        filing_type = classify_ca_filing(row.document)
        return InformationItem(
            source=self.name,
            source_type="regulatory_filing",
            external_id=f"ceoca-sedar-{row.spiel_id}",
            tickers=(ticker,),
            issuer=row.issuer,
            published_at=row.published_at,
            title=row.document,
            document_type=filing_type,
            url=row.url,
            collected_at=collected_at,
            raw_metadata={
                "provider": "ceo_ca",
                "source_tier": 4,
                "source_tier_label": "third_party_mirror",
                "is_official": False,
                "official_original_available": False,
                "cross_verified": False,
                "attachments_may_be_missing": True,
                "mirror_of": "SEDAR+",
                "coverage": "partial_undocumented_feed",
                "spiel_id": row.spiel_id,
                "original_ticker": row.ticker,
                "filing_type": filing_type,
                "mirror_document_type": "sedar_filing",
            },
            market=MARKET_CA,
            effective_at=row.published_at,
        )

    def _fetch_page(
        self, channel: str, user_agent: str, until: Optional[int]
    ) -> Mapping[str, Any]:
        params: dict[str, Any] = {"channel": channel, "limit": PAGE_SIZE}
        if until is not None:
            params["until"] = until
        request = Request(
            f"{API_BASE}?{urlencode(params)}",
            headers={"User-Agent": user_agent, "Accept": "application/json"},
        )
        try:
            with urlopen(request, timeout=30) as response:
                decoded = json.loads(response.read().decode("utf-8"))
        except (HTTPError, URLError, OSError, json.JSONDecodeError) as error:
            raise CeocaSedarRequestError(f"CEO.ca SEDAR request failed: {error}") from error
        if not isinstance(decoded, Mapping):
            raise CeocaSedarRequestError("CEO.ca SEDAR response is not an object")
        return decoded
