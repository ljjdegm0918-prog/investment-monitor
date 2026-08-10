"""European Mutual Funds (EMF) tradeable universe cache (breadth only).

EMF-2 spike (2026-08-10) found **no stable key-free ISIN-bearing European
mutual fund directory**:

* ESMA registers (registers.esma.europa.eu) expose public SOLR cores, but
  the funds core (``esma_registers_funds``, ~212k docs) contains only
  AIFMD reports (107,388 ``funds_report`` docs with legal frameworks
  AIF/EuVECA/ELTIF/EuSEF) plus marketing notifications - **no UCITS
  register and no ISIN field** (fund names/country/manager only).
* ``esma_registers_upreg`` is the MiFID investment-firms register, not
  funds.
* National fund registers (BaFin prospectus portal path 404, Bundesanzeiger
  session wall, CSSF/CBI search UIs) have no stable key-free ISIN export,
  and Morningstar/Lipper are paid products.

The cache shape is still provided: ``load_emf_universe`` /
``emf_universe_name_map`` / ``search_emf_universe`` read a locally cached
JSON payload if one ever exists (e.g. a future ESMA/regulator ISIN
directory slice), and ``refresh_emf_universe`` raises ``EmfUniverseError``
instead of faking a refresh or shipping a hand-written fund seed. The
cache is breadth only and never flows into information_items.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, List, Mapping, Optional

DEFAULT_CACHE_PATH = ".cache/investment_monitor/emf_universe.json"


class EmfUniverseError(RuntimeError):
    """Raised when the EMF universe cannot be refreshed at all."""


def load_emf_universe(
    path: Optional[Path] = None,
) -> Optional[Mapping[str, Any]]:
    """Load a cached EMF universe payload, or None when absent/invalid."""
    cache_path = _cache_path(path)
    try:
        with cache_path.open("r", encoding="utf-8") as cache_file:
            return json.load(cache_file)
    except (OSError, json.JSONDecodeError):
        return None


def refresh_emf_universe(
    *,
    path: Optional[Path] = None,
    opener=None,
    refreshed_at: Optional[str] = None,
) -> Mapping[str, Any]:
    """Refresh the EMF universe.

    No free ISIN-bearing European mutual fund directory source is wired
    (EMF-2 spike B2), so this always raises ``EmfUniverseError`` with the
    spike evidence instead of producing a fake or hand-written fund
    universe. The cache shape is reserved for a future slice that lands a
    real ESMA/national-regulator fund directory with ISINs.
    """
    raise EmfUniverseError(
        "EMF universe refresh is not wired: EMF-2 spike found no stable "
        "key-free ISIN-bearing European mutual fund directory (ESMA "
        "registers expose only AIFMD fund reports without ISINs and no "
        "UCITS core; national fund registers have no stable key-free ISIN "
        "export; Morningstar/Lipper are paid). See README European Mutual "
        "Funds section."
    )


def emf_universe_name_map(
    path: Optional[Path] = None,
) -> Mapping[str, Mapping[str, str]]:
    """Return ISIN -> {name, exchange, board, domicile} from a cache."""
    payload = load_emf_universe(path)
    if not payload:
        return {}
    result: dict = {}
    for item in payload.get("items") or []:
        isin = str(item.get("isin") or "").strip().upper()
        if not isin:
            continue
        result[isin] = {
            "name": str(item.get("name") or isin),
            "exchange": str(item.get("exchange") or "European Mutual Funds"),
            "board": str(item.get("board") or "UCITS"),
            "isin": isin,
            "domicile": str(item.get("domicile") or ""),
        }
    return result


def search_emf_universe(
    query: str,
    path: Optional[Path] = None,
) -> List[Mapping[str, Any]]:
    """Search the cached EMF universe by ISIN, name or domicile."""
    payload = load_emf_universe(path)
    if not payload:
        return []
    needle = str(query or "").strip().lower()
    if not needle:
        return []
    matches: List[Mapping[str, Any]] = []
    for item in payload.get("items") or []:
        haystack = (
            f"{item.get('isin') or ''} "
            f"{item.get('name') or ''} "
            f"{item.get('domicile') or ''}"
        ).lower()
        if needle in haystack:
            matches.append(dict(item))
        if len(matches) >= 50:
            break
    return matches


def _cache_path(path: Optional[Path]) -> Path:
    return Path(
        path or os.environ.get("EMF_UNIVERSE_CACHE_PATH", DEFAULT_CACHE_PATH)
    )
