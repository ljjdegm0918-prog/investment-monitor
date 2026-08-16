# -*- coding: utf-8 -*-
"""OpenFIGI v3 mapping client for the global equity reference.

P1-1. The public endpoint ``POST https://api.openfigi.com/v3/mapping``
works without an API key (verified 2026-08-15: GET returns 405, POST
returns JSON). Rate policy from the response headers is 25 requests per
60-second window, so requests are batched (default 10 jobs per request)
with a polite pause between batches.

The OpenFIGI stage is enrichment-only: it adds ``figi`` and ``figi_name``
but never rewrites official or EODHD display fields.
"""

from __future__ import annotations

import json
import logging
import os
import time
from typing import Any, Callable, Dict, List, Mapping, Optional
from urllib.request import Request, urlopen

LOGGER = logging.getLogger(__name__)

DEFAULT_BASE_URL = "https://api.openfigi.com/v3"
DEFAULT_TIMEOUT_SECONDS = 15.0
DEFAULT_MAX_CANDIDATES = 100
DEFAULT_JOBS_PER_REQUEST = 10
DEFAULT_PAUSE_SECONDS = 1.0
DEFAULT_USER_AGENT = "InvestmentMonitor/0.1 (internal workspace)"


class OpenFigiClientError(RuntimeError):
    """Raised when the OpenFIGI mapping request itself fails."""


def _default_opener() -> Callable[..., Any]:
    return urlopen


def _post_mapping(
    jobs: List[Mapping[str, str]],
    *,
    api_token: str,
    base_url: str,
    opener: Callable[..., Any],
    timeout: float,
) -> List[Mapping[str, Any]]:
    body = json.dumps(jobs).encode("utf-8")
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json",
        "User-Agent": DEFAULT_USER_AGENT,
    }
    if api_token:
        headers["X-OPENFIGI-APIKEY"] = api_token
    request = Request(
        f"{base_url.rstrip('/')}/mapping",
        data=body,
        headers=headers,
        method="POST",
    )
    with opener(request, timeout=timeout) as response:
        raw = response.read()
    payload = json.loads(raw.decode("utf-8"))
    if not isinstance(payload, list):
        raise OpenFigiClientError(
            f"OpenFIGI mapping returned {type(payload).__name__}, expected list"
        )
    return payload


def _pick_data(
    result: Mapping[str, Any],
    job: Mapping[str, str],
) -> Optional[Mapping[str, Any]]:
    data = result.get("data")
    if not isinstance(data, list) or not data:
        return None
    wanted_exchange = str(job.get("exchCode") or "")
    for record in data:
        if not isinstance(record, Mapping) or not record.get("figi"):
            continue
        if wanted_exchange and record.get("exchCode") != wanted_exchange:
            continue
        return record
    first = data[0]
    return first if isinstance(first, Mapping) and first.get("figi") else None


def enrich_with_openfigi(
    candidates: List[Mapping[str, Any]],
    *,
    api_token: str = "",
    base_url: str = DEFAULT_BASE_URL,
    opener: Optional[Callable[..., Any]] = None,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
    max_candidates: int = DEFAULT_MAX_CANDIDATES,
    jobs_per_request: int = DEFAULT_JOBS_PER_REQUEST,
    pause_seconds: float = DEFAULT_PAUSE_SECONDS,
) -> List[Dict[str, Any]]:
    """Add FIGI enrichment for ETF candidates that lack an ISIN/FIGI.

    The enrichment is deliberately scoped to ETF candidates (the Phase 1
    consumer) and capped so a full EODHD universe cannot exhaust the
    key-free 25 requests/minute window.
    """
    enriched = [dict(candidate) for candidate in candidates]
    token = (api_token or os.environ.get("OPENFIGI_API_KEY") or "").strip()

    target_rows: List[Dict[str, Any]] = []
    for row in enriched:
        if row.get("instrument_type") != "etf":
            continue
        if row.get("figi") and row.get("isin"):
            continue
        target_rows.append(row)
        if len(target_rows) >= max_candidates:
            break
    if not target_rows:
        return enriched

    jobs: List[Mapping[str, str]] = []
    for row in target_rows:
        isin = str(row.get("isin") or "").strip()
        if isin:
            jobs.append({"idType": "ID_ISIN", "idValue": isin})
        else:
            symbol = str(row.get("symbol") or "").strip()
            exchange = str(
                row.get("exchange") or row.get("board") or ""
            ).strip()
            if not symbol:
                continue
            job = {"idType": "ID_EXCH_SYMBOL", "idValue": symbol}
            if exchange:
                job["exchCode"] = exchange
            jobs.append(job)

    default_opener = opener or _default_opener()
    job_index = 0
    for batch_start in range(0, len(jobs), jobs_per_request):
        batch = jobs[batch_start : batch_start + jobs_per_request]
        results: List[Mapping[str, Any]] = []
        try:
            results = _post_mapping(
                batch,
                api_token=token,
                base_url=base_url,
                opener=default_opener,
                timeout=timeout,
            )
        except Exception as error:  # noqa: BLE001 - 富化失败不致命
            LOGGER.warning(
                "openfigi batch=%s failed: %s", batch_start, error
            )
            break
        for offset, result in enumerate(results):
            row_index = job_index + offset
            if row_index >= len(target_rows):
                continue
            record = _pick_data(result, batch[offset])
            if record is None:
                continue
            row = target_rows[row_index]
            row["figi"] = str(record.get("figi") or "")
            row["figi_name"] = str(record.get("name") or row.get("name") or "")
            row["figi_security_type"] = str(
                record.get("securityType") or ""
            )
            row["figi_exchange_code"] = str(record.get("exchCode") or "")
        job_index += len(batch)
        if pause_seconds and batch_start + jobs_per_request < len(jobs):
            time.sleep(pause_seconds)
    return enriched


__all__ = ["OpenFigiClientError", "enrich_with_openfigi"]
