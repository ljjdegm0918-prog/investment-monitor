"""AMF OAM regulatory disclosures connector for market=fr companies.

Collects French regulated disclosures from the key-free AMF OAM API. The
feed is keyed by company name (``societes[].raisonSociale``), not ticker,
so a record is emitted only when its company name or ISIN matches the FR
universe cache identity for a requested ticker. Requested FR tickers
without a universe identity are skipped and recorded in ``last_errors``
(never a fake success); the ticker mnemonic is never used as a name
pattern. Both a plain ``result`` list and an Elasticsearch
``hits.hits[]._source`` wrapper are accepted.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, List, Mapping, Optional, Sequence, Tuple
from urllib.parse import quote

from ...models import CollectionRequest, InformationItem, MARKET_FR
from ...universe.fr_universe import fr_universe_name_map
from ...web_repository import normalize_fr_ticker
from .client import AmfOamClient, AmfOamRequestError, _paris_day
from .matcher import AmfOamCompanyMatcher

LOGGER = logging.getLogger(__name__)

MAX_LOOKBACK_DAYS = 30


class AmfOamConnector:
    """Collect AMF OAM regulatory disclosures for market=fr companies."""

    name = "amf_oam"
    provider = "AMF OAM"
    max_lookback_days = MAX_LOOKBACK_DAYS

    def __init__(
        self,
        client: Optional[AmfOamClient] = None,
        universe: Optional[Mapping[str, Mapping[str, str]]] = None,
    ) -> None:
        self._client = client or AmfOamClient.from_environment()
        self._universe = (
            dict(universe) if universe is not None else fr_universe_name_map()
        )
        self._last_errors: Tuple[Tuple[str, str], ...] = ()

    @property
    def last_errors(self) -> Tuple[Tuple[str, str], ...]:
        return self._last_errors

    def collect(self, request: CollectionRequest) -> List[InformationItem]:
        failures: List[Tuple[str, str]] = []
        fr_tickers = tuple(
            normalize_fr_ticker(ticker)
            for ticker in request.tickers
            if request.market_for(ticker) == MARKET_FR
        )
        identities: List[Tuple[str, Mapping[str, str]]] = []
        for ticker in fr_tickers:
            identity = self._identity_for(ticker)
            if identity is None:
                failures.append((ticker, "no_universe_identity"))
                continue
            identities.append((ticker, identity))
        if not identities:
            # No FR ticker has a universe identity: nothing can be matched
            # and no HTTP request is made (non-fr requests stay at zero).
            self._last_errors = tuple(failures)
            return []

        collected_at = datetime.now(timezone.utc)
        try:
            limit = min(max(50, len(identities) * 10), 200)
            payload = self._client.fetch_payload(
                request.start_date, request.end_date, limit=limit
            )
            records = _parse_payload(
                payload,
                base_url=self._client.base_url,
                start_date=request.start_date,
                end_date=request.end_date,
            )
        except Exception as error:
            message = str(error) or error.__class__.__name__
            failures.extend((ticker, message) for ticker, _ in identities)
            LOGGER.warning("amf_oam status=failure error=%s", message)
            self._last_errors = tuple(failures)
            if len(request.tickers) == 1:
                raise AmfOamRequestError(message) from error
            return []

        matcher = AmfOamCompanyMatcher()
        items: List[InformationItem] = []
        for ticker, identity in identities:
            matched = [
                record
                for record in records
                if matcher.matches(
                    record,
                    name=identity.get("name") or "",
                    isin=identity.get("isin") or "",
                )
            ]
            items.extend(
                _map_records(
                    matched, ticker=ticker, collected_at=collected_at
                )
            )
        self._last_errors = tuple(failures)
        return items

    def _identity_for(
        self, ticker: str
    ) -> Optional[Mapping[str, str]]:
        identity = self._universe.get(ticker)
        if not identity:
            return None
        name = str(identity.get("name") or "").strip()
        isin = str(identity.get("isin") or "").strip().upper()
        if not name and not isin:
            return None
        return {"name": name, "isin": isin}


def _map_records(
    records: Sequence[Mapping[str, Any]],
    *,
    ticker: str,
    collected_at: datetime,
) -> List[InformationItem]:
    items: List[InformationItem] = []
    for record in records:
        external_id = str(record["external_id"])
        items.append(
            InformationItem(
                source="amf_oam", source_type="regulatory_filing",
                external_id=external_id, tickers=(ticker,),
                issuer=str(record.get("company") or ticker),
                published_at=record["published"],
                title=str(record["title"]),
                document_type=str(record["document_type"]),
                url=str(record["url"]),
                collected_at=collected_at,
                raw_metadata={
                    "provider": "amf_oam", "stock_code": ticker,
                    "document_id": external_id,
                    "document_path": str(record.get("document_path") or ""),
                    "company_name": str(record.get("company") or ""),
                },
                market=MARKET_FR, summary=None,
                effective_at=record["published"],
            )
        )
    return items


def _parse_payload(
    payload: Any, *, base_url: str, start_date, end_date,
) -> List[Mapping[str, Any]]:
    parsed: List[Mapping[str, Any]] = []
    for record in _extract_records(payload):
        if not isinstance(record, dict):
            continue
        external_id = str(
            record.get("numeroConcatene") or record.get("numero")
            or record.get("id") or ""
        ).strip()
        published = _parse_datetime(str(
            record.get("datePublication") or record.get("dateMiseEnLigne")
            or record.get("dateInformation") or ""
        ))
        if (not external_id or published is None
                or not start_date <= _paris_day(published) <= end_date):
            continue
        companies = _company_names(record)
        document_type = (
            _first(record, "typesDocument")
            or _first(record, "typesInformation") or "disclosure"
        )
        document_path = _doc_path(record)
        parsed.append({
            "external_id": external_id,
            "title": str(record.get("titre") or "").strip() or document_type,
            "published": published,
            "document_type": document_type,
            "url": (f"{base_url}/documents/{quote(document_path)}"
                    if document_path else base_url),
            "document_path": document_path,
            "company": companies[0] if companies else "",
            "companies": companies,
            "raw": record,
        })
    return parsed


def _extract_records(payload: Any) -> Sequence[Any]:
    if not isinstance(payload, dict):
        return ()
    result = payload.get("result")
    if isinstance(result, list):
        return result
    hits = payload.get("hits")
    if isinstance(hits, dict) and isinstance(hits.get("hits"), list):
        return tuple(row.get("_source") for row in hits["hits"]
                     if isinstance(row, dict)
                     and isinstance(row.get("_source"), dict))
    return ()


def _company_names(record: Mapping[str, Any]) -> List[str]:
    names: List[str] = []
    societes = record.get("societes")
    if isinstance(societes, list):
        names = [
            str(societe.get("raisonSociale") or "").strip()
            for societe in societes if isinstance(societe, dict)
        ]
        names = [name for name in names if name]
    if not names:
        for key in ("societe", "nomSociete", "emetteur", "issuer"):
            name = str(record.get(key) or "").strip()
            if name:
                names.append(name)
    return names


def _doc_path(record: Mapping[str, Any]) -> str:
    documents = record.get("documents")
    if isinstance(documents, list):
        for document in documents:
            if isinstance(document, dict) and str(document.get("path") or "").strip():
                return str(document["path"]).strip()
    return ""


def _first(record: Mapping[str, Any], key: str) -> str:
    value = record.get(key)
    if isinstance(value, list):
        return next((str(entry) for entry in value if entry), "")
    return str(value or "")


def _parse_datetime(value: str) -> Optional[datetime]:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
