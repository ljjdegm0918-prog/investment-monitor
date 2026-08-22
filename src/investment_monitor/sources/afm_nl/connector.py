"""Map the official AFM register to monitored Dutch securities."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, List, Mapping, Optional, Tuple

from ...models import CollectionRequest, InformationItem, MARKET_NL
from ...provenance import build_raw_provenance
from ...universe.nl_universe import nl_universe_name_map
from ...web_repository import normalize_nl_ticker
from .._public_disclosure import record_matches
from .client import AfmNlClient, AfmNlRequestError


def _filing_type(title: str) -> str:
    value = title.casefold()
    if any(term in value for term in ("annual report", "jaarverslag", "annual results")):
        return "annual_report"
    if any(term in value for term in ("half-year", "half year", "quarter", "results", "cijfers")):
        return "financial_results"
    if any(term in value for term in ("share buyback", "own shares", "inkoop eigen aandelen")):
        return "share_buyback"
    if any(term in value for term in ("acquisition", "disposal", "overname", "divest")):
        return "acquisition_disposal"
    if any(term in value for term in ("dividend", "distribution")):
        return "dividend"
    if any(term in value for term in ("appointment", "resignation", "board", "management")):
        return "management_change"
    if any(term in value for term in ("financing", "bond", "loan", "offering", "placement")):
        return "financing"
    return "material_change"


class AfmNlConnector:
    """Official AFM Article 17 register; unmatched identities stay auditable."""

    name = "afm_nl"
    provider = "AFM inside-information register"
    max_lookback_days = 30
    coverage_level = "official_mar_article_17_register"

    def __init__(
        self,
        client: Optional[AfmNlClient] = None,
        universe: Optional[Mapping[str, Mapping[str, str]]] = None,
    ) -> None:
        self._client = client or AfmNlClient()
        self._universe = dict(
            universe if universe is not None else nl_universe_name_map()
        )
        self._last_errors: Tuple[Tuple[str, str], ...] = ()
        self.last_collection_status = "empty"
        self.last_records_read = 0
        self.last_unmatched_records = 0
        self.last_pending_records: Tuple[Mapping[str, Any], ...] = ()

    @property
    def last_errors(self) -> Tuple[Tuple[str, str], ...]:
        return self._last_errors

    def collect(self, request: CollectionRequest) -> List[InformationItem]:
        tickers = tuple(
            dict.fromkeys(
                normalize_nl_ticker(ticker)
                for ticker in request.tickers
                if request.market_for(ticker) == MARKET_NL
            )
        )
        if not tickers:
            self._reset("empty")
            return []
        try:
            records = tuple(self._client.fetch(request.start_date, request.end_date))
        except Exception as error:
            message = str(error) or error.__class__.__name__
            self._last_errors = (("*", message),)
            self.last_collection_status = "unavailable"
            self.last_records_read = 0
            self.last_unmatched_records = 0
            self.last_pending_records = ()
            raise AfmNlRequestError(message) from error

        self.last_records_read = len(records)
        pending = []
        items: List[InformationItem] = []
        collected_at = datetime.now(timezone.utc)
        for record in records:
            matched = tuple(
                ticker
                for ticker in tickers
                if record_matches(
                    record,
                    ticker,
                    self._universe.get(ticker, {}),
                    normalize_nl_ticker,
                )
            )
            if not matched:
                pending.append(
                    {
                        "external_id": record.get("external_id"),
                        "issuer": record.get("issuer"),
                        "title": record.get("title"),
                        "published_at": record.get("published_at"),
                        "url": record.get("url"),
                        "match_status": "pending_matching",
                    }
                )
            identity = self._universe.get(matched[0], {}) if matched else {}
            source_url = str(record["url"])
            native_id = str(record.get("native_id") or record["external_id"])
            filing_type = _filing_type(str(record["title"]))
            items.append(
                InformationItem(
                    source=self.name,
                    source_type="regulatory_filing",
                    external_id=str(record["external_id"]),
                    tickers=matched,
                    issuer=str(record["issuer"]),
                    published_at=record["published_at"],
                    title=str(record["title"]),
                    document_type=filing_type,
                    url=source_url,
                    collected_at=collected_at,
                    raw_metadata={
                        **build_raw_provenance(
                            official_source_id=native_id,
                            official_source_url=source_url,
                            retrieval_url=str(record.get("retrieval_url") or ""),
                            raw_payload=record.get("raw_payload") or record,
                            raw_payload_format="html",
                            classification_code="mar_article_17",
                            classification_label="AFM inside information",
                            published_at_raw=str(record.get("published_at_raw") or ""),
                            published_timezone="Europe/Amsterdam",
                        ),
                        "source_tier": 1,
                        "source_tier_label": "regulator_official",
                        "regulator": "AFM",
                        "official_document": True,
                        "officiality": "official_regulatory_register",
                        "afm_record_id": native_id,
                        "isin": str(identity.get("isin") or "") or None,
                        "match_status": "matched" if matched else "pending_matching",
                        "identity_candidates": {
                            "issuer": str(record.get("issuer") or "") or None,
                            "isin": None,
                            "ticker": None,
                        },
                        "filing_type": filing_type,
                        "attachments": [],
                        "attachment_urls": [],
                        "attachments_may_be_missing": True,
                        "coverage_level": self.coverage_level,
                    },
                    market=MARKET_NL,
                    summary=None,
                    effective_at=record["published_at"],
                )
            )
        self._last_errors = ()
        self.last_pending_records = tuple(pending)
        self.last_unmatched_records = len(pending)
        if pending:
            self.last_collection_status = "partial"
        else:
            self.last_collection_status = "success" if items else "empty"
        return items

    def _reset(self, status: str) -> None:
        self._last_errors = ()
        self.last_collection_status = status
        self.last_records_read = 0
        self.last_unmatched_records = 0
        self.last_pending_records = ()


__all__ = ["AfmNlConnector"]
