# -*- coding: utf-8 -*-
"""Static 28-country / 87-stock-venue comparison benchmark.

The catalog is the Phase 0 "exchange directory" layer. It is static seed
data (originally normalized from a public broker products/exchanges snapshot; see the
``normalization`` block in :file:`ibkr_exchange_catalog.json`) and never
flows into information_items / the daily feed. Routing venues (BATS,
Cboe, Turquoise, Aquis, …) are recorded as *venues*, not as issuer
disclosure connectors.

This packaged snapshot is provenance, not a broker integration. Loading it
requires no account, credential, network request, or runtime broker service.

Counts are the frozen Phase 0 contract and are asserted by tests:
28 core countries (Americas 3, Europe 19, Asia 6) and 87 stock venues
(Americas 31, Europe 44, Asia 12). Extra repo markets
(cn/kr/aq/cxe/trq/eux/emf) are stored as ``extra_entries`` with
``catalog_role`` and never enter the 28-country denominator.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional

LOGGER = logging.getLogger(__name__)

DEFAULT_SEED_PATH = Path(__file__).with_name("ibkr_exchange_catalog.json")

_CACHE: Dict[Path, Mapping[str, Any]] = {}


class ExchangeCatalogError(RuntimeError):
    """Raised when the catalog seed is missing or structurally invalid."""


def load_exchange_catalog(
    path: Optional[Path] = None,
) -> Mapping[str, Any]:
    """Load the catalog seed (cached per path)."""
    seed_path = Path(path) if path is not None else DEFAULT_SEED_PATH
    if seed_path in _CACHE:
        return _CACHE[seed_path]
    if not seed_path.exists():
        raise ExchangeCatalogError(f"reference exchange catalog missing: {seed_path}")
    try:
        with seed_path.open("r", encoding="utf-8") as handle:
            payload = json.load(handle)
    except (OSError, json.JSONDecodeError) as error:
        raise ExchangeCatalogError(
            f"reference exchange catalog unreadable: {seed_path}: {error}"
        ) from error
    if not isinstance(payload, Mapping):
        raise ExchangeCatalogError("reference exchange catalog must be a JSON object")
    _CACHE[seed_path] = payload
    return payload


def list_countries(
    *,
    include_extra: bool = False,
    path: Optional[Path] = None,
) -> List[Dict[str, Any]]:
    """Return core country rows; ``include_extra`` adds non-28 repo markets."""
    catalog = load_exchange_catalog(path)
    rows = [dict(item) for item in catalog.get("countries") or []]
    if include_extra:
        rows.extend(dict(item) for item in catalog.get("extra_entries") or [])
    return rows


def list_venues(
    country: Optional[str] = None,
    *,
    path: Optional[Path] = None,
) -> List[Dict[str, Any]]:
    """Return stock venue rows, optionally filtered by country code."""
    catalog = load_exchange_catalog(path)
    wanted = (country or "").strip().upper()
    rows: List[Dict[str, Any]] = []
    for item in catalog.get("venues") or []:
        if wanted and str(item.get("country_code") or "").upper() != wanted:
            continue
        rows.append(dict(item))
    return rows


def country_count(*, include_extra: bool = False, path: Optional[Path] = None) -> int:
    """Core country count; 28 by contract (never includes extra entries)."""
    return len(list_countries(include_extra=include_extra, path=path))


def venue_count(
    country: Optional[str] = None,
    *,
    path: Optional[Path] = None,
) -> int:
    """Stock venue count; 87 by contract, or the per-country slice."""
    return len(list_venues(country, path=path))


def primary_exchanges_for(
    country: str,
    *,
    path: Optional[Path] = None,
) -> List[str]:
    """Primary reference venue ids for one country."""
    wanted = country.strip().upper()
    for item in list_countries(path=path):
        if str(item.get("country_code") or "").upper() == wanted:
            return [str(v) for v in item.get("primary_exchange") or []]
    return []


def catalog_summary(path: Optional[Path] = None) -> Dict[str, Any]:
    """Readable summary used by the coverage API and the web board."""
    catalog = load_exchange_catalog(path)
    regions: Dict[str, Dict[str, int]] = {}
    for item in catalog.get("countries") or []:
        region = str(item.get("region") or "Other")
        bucket = regions.setdefault(region, {"countries": 0, "venues": 0})
        bucket["countries"] += 1
    for item in catalog.get("venues") or []:
        region = str(item.get("region") or "Other")
        regions.setdefault(region, {"countries": 0, "venues": 0})["venues"] += 1
    return {
        "schema_version": int(catalog.get("schema_version") or 0),
        "updated_at": str(catalog.get("updated_at") or ""),
        "source": str(catalog.get("source") or ""),
        "countries": len(catalog.get("countries") or []),
        "venues": len(catalog.get("venues") or []),
        "regions": regions,
        "extra_entries": len(catalog.get("extra_entries") or []),
    }


__all__ = [
    "ExchangeCatalogError",
    "catalog_summary",
    "country_count",
    "list_countries",
    "list_venues",
    "load_exchange_catalog",
    "primary_exchanges_for",
    "venue_count",
]
