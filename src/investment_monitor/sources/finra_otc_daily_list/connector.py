"""Official FINRA OTC Daily List corporate actions for requested symbols."""

from __future__ import annotations

from datetime import datetime, timezone
from hashlib import sha256
from typing import List, Mapping, Optional, Tuple
from zoneinfo import ZoneInfo

from ...models import CollectionRequest, InformationItem, MARKET_US
from ...provenance import build_raw_provenance
from ...universe.finra_otc import API_ROOT, FinraOtcClient, FinraOtcError
from ...us_universe import us_universe_name_map

NEW_YORK = ZoneInfo("America/New_York")
PUBLIC_URL = "https://otce.finra.org/otce/dailyList"
DATA_URL = f"{API_ROOT}/data/group/otcMarket/name/otcDailyList"


class FinraOtcDailyListConnector:
    """Collect additions, deletions and corporate actions from FINRA."""

    name = "finra_otc_daily_list"
    provider = "FINRA OTC Daily List"
    source_wide_collection = True
    max_lookback_days = 30

    def __init__(
        self,
        client: Optional[FinraOtcClient] = None,
        universe: Optional[Mapping[str, Mapping[str, object]]] = None,
    ) -> None:
        self._client = client or FinraOtcClient.from_environment()
        loaded_universe = universe if universe is not None else us_universe_name_map()
        self._universe = dict(loaded_universe)
        self._universe_ready = universe is not None or bool(loaded_universe)
        self._last_errors: Tuple[Tuple[str, str], ...] = ()
        self.last_collection_status = "empty"
        self.last_records_read = 0
        self.last_matched_records = 0

    @property
    def last_errors(self) -> Tuple[Tuple[str, str], ...]:
        return self._last_errors

    def collect(self, request: CollectionRequest) -> List[InformationItem]:
        us_tickers = tuple(
            ticker
            for ticker in request.tickers
            if request.market_for(ticker) == MARKET_US
        )
        if us_tickers and not self._universe_ready:
            message = "US universe cache is unavailable; run the daily US refresh"
            self._last_errors = (("*", message),)
            self.last_collection_status = "unavailable"
            self.last_records_read = 0
            self.last_matched_records = 0
            raise FinraOtcError(message)
        targets = {
            str(ticker or "").strip().upper()
            for ticker in request.tickers
            if request.market_for(ticker) == MARKET_US
            and _is_otc_identity(
                self._universe.get(str(ticker or "").strip().upper(), {})
            )
        }
        if not targets:
            self._last_errors = ()
            self.last_collection_status = "empty"
            self.last_records_read = 0
            self.last_matched_records = 0
            return []
        try:
            records = self._client.fetch_daily_list(
                request.start_date,
                request.end_date,
            )
        except Exception as error:
            message = str(error) or error.__class__.__name__
            self._last_errors = (("*", message),)
            self.last_collection_status = "failure"
            self.last_records_read = int(
                getattr(self._client, "last_daily_list_total", 0) or 0
            )
            self.last_matched_records = 0
            raise FinraOtcError(message) from error

        collected_at = datetime.now(timezone.utc)
        items: List[InformationItem] = []
        for record in records:
            symbols = tuple(
                dict.fromkeys(
                    str(record.get(field) or "").strip().upper()
                    for field in ("oldSymbolCode", "newSymbolCode")
                    if str(record.get(field) or "").strip()
                )
            )
            matched = tuple(symbol for symbol in symbols if symbol in targets)
            if not matched:
                continue
            timestamp = _published_at(str(record["dailyListDatetime"]))
            reason = str(record["dailyListReasonDescription"])
            identity = str(record["row_identity"])
            native_id = sha256(identity.encode("utf-8")).hexdigest()[:24]
            external_id = f"finra-otc-daily:{native_id}"
            issuer = _issuer_name(record, matched[0], self._universe)
            title = _title(record, reason, issuer)
            items.append(
                InformationItem(
                    source=self.name,
                    source_type="regulatory_filing",
                    external_id=external_id,
                    tickers=matched,
                    issuer=issuer,
                    published_at=timestamp,
                    title=title,
                    document_type=_document_type(reason),
                    url=PUBLIC_URL,
                    collected_at=collected_at,
                    raw_metadata={
                        **build_raw_provenance(
                            official_source_id=external_id,
                            official_source_url=PUBLIC_URL,
                            retrieval_url=DATA_URL,
                            raw_payload=record,
                            raw_payload_format="json",
                            classification_code=str(
                                record.get("subjectCorporateActionCode") or ""
                            ),
                            classification_label=reason,
                            published_at_raw=str(record["dailyListDatetime"]),
                            published_timezone="America/New_York",
                        ),
                        "provider": self.provider,
                        "source_tier": 1,
                        "official_document": True,
                        "coverage_level": "official_otc_corporate_actions",
                        "old_symbol": record.get("oldSymbolCode"),
                        "new_symbol": record.get("newSymbolCode"),
                        "old_market_category": record.get("oldMarketCategoryCode"),
                        "new_market_category": record.get("newMarketCategoryCode"),
                        "ex_date": record.get("exDate"),
                        "declaration_date": record.get("declarationDate"),
                        "record_date": record.get("recordDate"),
                        "payment_date": record.get("paymentDate"),
                        "cash_amount": record.get("cashAmountText"),
                        "forward_split_rate": record.get("forwardSplitRate"),
                        "reverse_split_rate": record.get("reverseSplitRate"),
                        "dividend_type": record.get("dividendTypeCode"),
                        "financial_status_before": record.get(
                            "oldFinancialStatusCode"
                        ),
                        "financial_status_after": record.get(
                            "newFinancialStatusCode"
                        ),
                        "partition_dates": list(
                            getattr(self._client, "last_partition_dates", ())
                        ),
                        "match_status": "matched_by_finra_symbol",
                        "attachments": [],
                    },
                    market=MARKET_US,
                    summary=str(record.get("commentText") or "") or None,
                    effective_at=timestamp,
                )
            )

        self._last_errors = ()
        self.last_records_read = int(
            getattr(self._client, "last_daily_list_total", len(records)) or 0
        )
        self.last_matched_records = len(items)
        self.last_collection_status = "success" if items else "empty"
        return items


def _is_otc_identity(identity: Mapping[str, object]) -> bool:
    value = identity.get("otc")
    return value is True or str(value).casefold() == "true"


def _published_at(raw: str) -> datetime:
    try:
        return datetime.strptime(raw, "%Y-%m-%d %H:%M:%S.%f").replace(
            tzinfo=NEW_YORK
        )
    except ValueError as error:
        raise FinraOtcError("FINRA OTC Daily List timestamp is invalid") from error


def _issuer_name(
    record: Mapping[str, object],
    ticker: str,
    universe: Mapping[str, Mapping[str, object]],
) -> str:
    return str(
        record.get("newSecurityDescription")
        or record.get("oldSecurityDescription")
        or universe.get(ticker, {}).get("name")
        or ticker
    ).strip()


def _title(record: Mapping[str, object], reason: str, issuer: str) -> str:
    old_symbol = str(record.get("oldSymbolCode") or "").strip()
    new_symbol = str(record.get("newSymbolCode") or "").strip()
    transition = (
        f" ({old_symbol} → {new_symbol})"
        if old_symbol and new_symbol and old_symbol != new_symbol
        else ""
    )
    return f"{reason}: {issuer}{transition}"


def _document_type(reason: str) -> str:
    value = reason.casefold()
    if "dividend" in value or "distribution" in value:
        return "dividend"
    if "split" in value:
        return "stock_split"
    if "bankrupt" in value:
        return "bankruptcy"
    if "deletion" in value:
        return "trading_deletion"
    if "addition" in value:
        return "trading_addition"
    if "symbol" in value or "name change" in value:
        return "symbol_name_change"
    if "conversion" in value or "reclassification" in value:
        return "reclassification"
    return "other_corporate_action"


__all__ = ["FinraOtcDailyListConnector"]
