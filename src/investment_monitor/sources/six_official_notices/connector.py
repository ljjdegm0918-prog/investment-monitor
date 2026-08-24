"""SIX Exchange Regulation official notices for requested Swiss securities."""

from __future__ import annotations

from datetime import datetime, timezone
import re
from typing import List, Mapping, Optional, Tuple

from ...models import CollectionRequest, InformationItem, MARKET_CH
from ...provenance import build_raw_provenance
from ...universe.ch_universe import ch_universe_name_map
from ...web_repository import normalize_ch_ticker
from .client import SixOfficialNoticesClient, SixOfficialNoticesError

_ISIN = re.compile(r"[A-Z]{2}[A-Z0-9]{10}")


class SixOfficialNoticesConnector:
    """Collect only notices whose list-row ISIN matches a requested security."""

    name = "six_official_notices"
    provider = "SIX Exchange Regulation Official Notices"
    source_wide_collection = True
    max_lookback_days = 30

    def __init__(
        self,
        client: Optional[SixOfficialNoticesClient] = None,
        universe: Optional[Mapping[str, Mapping[str, str]]] = None,
    ) -> None:
        self._client = client or SixOfficialNoticesClient.from_environment()
        self._universe = dict(
            universe if universe is not None else ch_universe_name_map()
        )
        self._last_errors: Tuple[Tuple[str, str], ...] = ()
        self.last_collection_status = "empty"
        self.last_records_read = 0
        self.last_matched_records = 0

    @property
    def last_errors(self) -> Tuple[Tuple[str, str], ...]:
        return self._last_errors

    def collect(self, request: CollectionRequest) -> List[InformationItem]:
        failures: List[Tuple[str, str]] = []
        isin_to_tickers: dict[str, List[str]] = {}
        identity_by_ticker: dict[str, Mapping[str, str]] = {}
        for raw_ticker in request.tickers:
            if request.market_for(raw_ticker) != MARKET_CH:
                continue
            ticker = normalize_ch_ticker(raw_ticker)
            identity = self._universe.get(ticker, {})
            isin = (
                ticker
                if _ISIN.fullmatch(ticker)
                else str(identity.get("isin") or "").strip().upper()
            )
            if not _ISIN.fullmatch(isin):
                failures.append((ticker, "no_universe_isin"))
                continue
            isin_to_tickers.setdefault(isin, []).append(ticker)
            identity_by_ticker[ticker] = identity
        if not isin_to_tickers:
            self._last_errors = tuple(failures)
            self.last_collection_status = "unavailable" if failures else "empty"
            self.last_records_read = 0
            self.last_matched_records = 0
            return []

        try:
            records = self._client.fetch_for_isins(
                tuple(isin_to_tickers), request.start_date, request.end_date
            )
        except Exception as error:
            message = str(error) or error.__class__.__name__
            self._last_errors = tuple([*failures, ("*", message)])
            self.last_collection_status = "failure"
            self.last_records_read = int(
                getattr(self._client, "last_list_records", 0) or 0
            )
            self.last_matched_records = 0
            raise SixOfficialNoticesError(message) from error

        collected_at = datetime.now(timezone.utc)
        items: List[InformationItem] = []
        for record in records:
            matched_isins = tuple(
                str(value).strip().upper()
                for value in record.get("matched_isins") or ()
            )
            matched = tuple(
                dict.fromkeys(
                    ticker
                    for isin in matched_isins
                    for ticker in isin_to_tickers.get(isin, ())
                )
            )
            if not matched:
                raise SixOfficialNoticesError(
                    "SIX Official Notices client returned an unrequested ISIN"
                )
            issuer = str(record.get("issuer") or "").strip()
            if not issuer:
                issuer = str(identity_by_ticker.get(matched[0], {}).get("name") or matched[0])
            external_id = str(record["external_id"])
            source_url = str(record["url"])
            raw_payload = record.get("raw_payload") or dict(record)
            published_at = record["published_at"]
            if not isinstance(published_at, datetime):
                raise SixOfficialNoticesError(
                    "SIX Official Notices record has no publication datetime"
                )
            items.append(
                InformationItem(
                    source=self.name,
                    source_type="regulatory_filing",
                    external_id=external_id,
                    tickers=matched,
                    issuer=issuer,
                    published_at=published_at,
                    title=str(record["title"]),
                    document_type=str(record["document_type"]),
                    url=source_url,
                    collected_at=collected_at,
                    raw_metadata={
                        **build_raw_provenance(
                            official_source_id=external_id,
                            official_source_url=source_url,
                            retrieval_url=str(record.get("retrieval_url") or ""),
                            raw_payload=raw_payload,
                            raw_payload_format="json",
                            classification_code=str(
                                record.get("classification_code") or ""
                            ),
                            classification_label=str(record["document_type"]),
                            published_at_raw=str(
                                record.get("published_at_raw") or ""
                            ),
                            published_timezone="Europe/Zurich",
                        ),
                        "provider": self.provider,
                        "source_tier": 1,
                        "official_document": True,
                        "coverage_level": "official_notice_events",
                        "isin": matched_isins[0] if len(matched_isins) == 1 else None,
                        "isins": list(record.get("isins") or []),
                        "matched_isins": list(matched_isins),
                        "isin_raw": record.get("isin_raw"),
                        "valor_number": record.get("valor_number"),
                        "official_notice_number": record.get(
                            "official_notice_number"
                        ),
                        "list_retrieval_url": record.get("list_retrieval_url"),
                        "attachments": list(record.get("attachments") or []),
                        "match_status": "matched_by_isin",
                    },
                    market=MARKET_CH,
                    summary=str(record.get("summary") or "") or None,
                    effective_at=published_at,
                )
            )

        self._last_errors = tuple(failures)
        self.last_records_read = int(
            getattr(self._client, "last_list_records", len(records)) or 0
        )
        self.last_matched_records = len(items)
        if failures and items:
            self.last_collection_status = "partial"
        elif failures:
            self.last_collection_status = "unavailable"
        else:
            self.last_collection_status = "success" if items else "empty"
        return items


__all__ = ["SixOfficialNoticesConnector"]
