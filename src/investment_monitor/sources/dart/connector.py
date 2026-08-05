"""OpenDART disclosure connector for market=kr companies."""

from __future__ import annotations

import logging
import os
from datetime import date, datetime, time, timezone
from pathlib import Path
from typing import Any, List, Mapping, Optional, Tuple

from ...connectors.base import ConnectorUnavailableError, SecretField
from ...models import CollectionRequest, InformationItem, MARKET_KR
from .client import (
    DartClient,
    DartRequestError,
    _redact_secrets,
)
from .corp_code_cache import CorpCodeCache, DEFAULT_CACHE_TTL_SECONDS

LOGGER = logging.getLogger(__name__)

MAX_LOOKBACK_DAYS = 30
DART_VIEWER_URL = "https://dart.fss.or.kr/dsaf001/main.do?rcpNo={rcept_no}"
DART_REPORT_TYPES = {
    "B001": "annual_report",
    "C001": "quarterly_report",
    "D001": "semi_annual_report",
    "E001": "other_report",
    "A001": "disclosure",
}


class DARTConnector:
    """Collect official OpenDART disclosures for active KR companies."""

    name = "dart"
    provider = "OpenDART"
    max_lookback_days = MAX_LOOKBACK_DAYS
    secret_fields = (
        SecretField(
            env="DART_API_KEY",
            label="OpenDART API Key",
            kind="password",
            help=(
                "OpenDART API key (crtfc_key) issued at "
                "https://opendart.fss.or.kr. Leave blank to keep the "
                "current value; Clear removes it."
            ),
        ),
    )

    def __init__(
        self,
        client: Optional[DartClient] = None,
        cache: Optional[CorpCodeCache] = None,
    ) -> None:
        self._client = client or DartClient.from_environment()
        self._cache = cache or CorpCodeCache(
            client=self._client,
            cache_path=Path(
                os.environ.get(
                    "DART_CORP_CODE_CACHE_PATH",
                    ".cache/investment_monitor/dart_corp_codes.json",
                )
            ),
            ttl_seconds=_read_cache_ttl(),
        )
        self._last_errors: Tuple[Tuple[str, str], ...] = ()

    @classmethod
    def configuration_error(cls) -> Optional[str]:
        """Return a reason when the source cannot be enabled."""
        if not os.environ.get("DART_API_KEY", "").strip():
            return (
                "DART_API_KEY is not configured; OpenDART is not connected."
            )
        return None

    @classmethod
    def from_environment(cls) -> "DARTConnector":
        """Build a production connector from environment configuration."""
        configuration_error = cls.configuration_error()
        if configuration_error is not None:
            raise ConnectorUnavailableError(configuration_error)
        return cls(client=DartClient.from_environment())

    @property
    def last_errors(self) -> Tuple[Tuple[str, str], ...]:
        """(ticker, message) pairs from the most recent collect call."""
        return self._last_errors

    def collect(self, request: CollectionRequest) -> List[InformationItem]:
        """Collect disclosures per ticker; non-KR or unmapped tickers skip."""
        items: List[InformationItem] = []
        failures: List[Tuple[str, str]] = []
        collected_at = datetime.now(timezone.utc)

        for ticker in request.tickers:
            market = request.market_for(ticker)
            if market != MARKET_KR:
                LOGGER.info(
                    "dart ticker=%s market=%s skipped not_kr_market",
                    ticker,
                    market,
                )
                continue
            try:
                resolved = self._cache.resolve(ticker)
            except Exception as error:
                message = _redact_secrets(
                    str(error) or error.__class__.__name__
                )
                failures.append((ticker, message))
                LOGGER.warning(
                    "dart ticker=%s status=failure error=%s",
                    ticker,
                    message,
                )
                continue
            if resolved is None:
                LOGGER.info(
                    "dart ticker=%s skipped no_corp_code",
                    ticker,
                )
                continue
            corp_code, corp_name, normalized_ticker = resolved
            try:
                records = self._client.get_list(
                    corp_code=corp_code,
                    bgn_de=request.start_date.strftime("%Y%m%d"),
                    end_de=request.end_date.strftime("%Y%m%d"),
                )
                items.extend(
                    self._map_records(
                        records,
                        ticker=normalized_ticker,
                        corp_code=corp_code,
                        corp_name=corp_name,
                        start_date=request.start_date,
                        end_date=request.end_date,
                        collected_at=collected_at,
                    )
                )
            except Exception as error:
                message = _redact_secrets(
                    str(error) or error.__class__.__name__
                )
                failures.append((ticker, message))
                LOGGER.warning(
                    "dart ticker=%s status=failure error=%s",
                    ticker,
                    message,
                )

        self._last_errors = tuple(failures)
        if len(request.tickers) == 1 and failures:
            raise DartRequestError(failures[0][1])
        return items

    def _map_records(
        self,
        records: List[Mapping[str, Any]],
        *,
        ticker: str,
        corp_code: str,
        corp_name: str,
        start_date: date,
        end_date: date,
        collected_at: datetime,
    ) -> List[InformationItem]:
        items: List[InformationItem] = []
        for record in records:
            if not isinstance(record, dict):
                continue
            rcept_no = str(record.get("rcept_no") or "").strip()
            report_nm = str(record.get("report_nm") or "").strip()
            if not rcept_no or not report_nm:
                continue
            published_at = _parse_rcept_dt(
                str(record.get("rcept_dt") or "").strip()
            )
            if published_at is None:
                continue
            if not start_date <= published_at.date() <= end_date:
                continue
            en_title = (
                str(record.get("en_title") or "").strip() or None
            )
            raw_metadata: Mapping[str, Any] = {
                "provider": "opendart",
                "corp_code": corp_code,
                "rcept_no": rcept_no,
                "rcept_dt": str(record.get("rcept_dt") or ""),
                "report_nm": report_nm,
                "corp_name": corp_name,
            }
            for field in ("flr_nm", "rm", "pblntf_ty"):
                value = record.get(field)
                if value not in (None, ""):
                    raw_metadata[field] = str(value)
            if en_title:
                raw_metadata["en_title"] = en_title
            items.append(
                InformationItem(
                    source=self.name,
                    source_type="regulatory_filing",
                    external_id=rcept_no,
                    tickers=(ticker,),
                    issuer=corp_name,
                    published_at=published_at,
                    title=report_nm,
                    document_type=_document_type(record.get("pblntf_ty")),
                    url=DART_VIEWER_URL.format(rcept_no=rcept_no),
                    collected_at=collected_at,
                    raw_metadata=dict(raw_metadata),
                    market=MARKET_KR,
                    summary=en_title,
                    effective_at=published_at,
                )
            )
        return items


def _document_type(value: Any) -> str:
    return DART_REPORT_TYPES.get(
        str(value or "").strip(),
        "dart_report",
    )


def _parse_rcept_dt(value: str) -> Optional[datetime]:
    if not value:
        return None
    try:
        parsed = datetime.strptime(value, "%Y%m%d").date()
    except ValueError:
        return None
    return datetime.combine(parsed, time.min, tzinfo=timezone.utc)


def _read_cache_ttl() -> float:
    value = os.environ.get("DART_CORP_CODE_TTL_SECONDS")
    if value is None:
        return DEFAULT_CACHE_TTL_SECONDS
    try:
        result = float(value)
    except ValueError as error:
        raise ValueError(
            "DART_CORP_CODE_TTL_SECONDS must be a number."
        ) from error
    if result < 0:
        raise ValueError(
            "DART_CORP_CODE_TTL_SECONDS must not be negative."
        )
    return result
