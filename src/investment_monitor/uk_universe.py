"""UK tradeable universe cache (breadth only) from FCA FIRDS.

FIRDS is a regulatory instrument-reference dataset (ISIN / LEI / trading
venues / names); it does NOT carry ticker mnemonics. This module keeps an
ISIN-keyed local cache and enriches UK equities with tickers via the free
OpenFIGI mapping API (anonymous, key-free at low volume), plus a small
verified ticker->ISIN seed for blue chips. It never flows into
information_items. The full daily FULINS set is large (many split ZIP/XML
files), so refresh is opt-in and supports ``max_parts`` for incremental
validation.
"""

from __future__ import annotations

import io
import json
import logging
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Mapping, Optional
from urllib.parse import urlencode
from urllib.request import Request, urlopen
import xml.etree.ElementTree as ElementTree
import zipfile

LOGGER = logging.getLogger(__name__)

DEFAULT_CACHE_PATH = ".cache/investment_monitor/uk_universe.json"
FIRDS_LIST_URL = "https://api.data.fca.org.uk/fca_data_firds_files"
FIRDS_FILE_PREFIX = "https://data.fca.org.uk/artefacts/FIRDS/"
UK_VENUE_MICS = frozenset({"XLON"})
REQUEST_SLEEP_SECONDS = 1.0
OPENFIGI_MAPPING_URL = "https://api.openfigi.com/v3/mapping"
OPENFIGI_BATCH_SIZE = 100
OPENFIGI_REQUEST_SLEEP_SECONDS = 1.0

# Best-effort public ISINs for common UK blue chips. Only used to give
# ticker keys to FIRDS ISIN records; a wrong ISIN simply yields no ticker.
TICKER_ISIN_SEED = {
    "VOD": "GB00BH4HKS39",
    "BP.": "GB0007980591",
    "SHEL": "GB00BP6MXD84",
    "HSBA": "GB0005405286",
    "AZN": "GB0009895292",
    "GSK": "GB00BN7SWP63",
    "DGE": "GB0002374006",
    "BARC": "GB0031348658",
    "ULVR": "GB00B10RZP78",
}


class UkUniverseError(RuntimeError):
    """Raised when the UK universe cannot be refreshed."""


def load_uk_universe(
    path: Optional[Path] = None,
) -> Optional[Mapping[str, Any]]:
    """Load the cached universe payload, or None when absent/invalid."""
    cache_path = _cache_path(path)
    try:
        with cache_path.open("r", encoding="utf-8") as cache_file:
            return json.load(cache_file)
    except (OSError, json.JSONDecodeError):
        return None


def refresh_uk_universe(
    *,
    path: Optional[Path] = None,
    source: Optional[str] = None,
    max_parts: Optional[int] = None,
    enrich_tickers: Optional[bool] = None,
    openfigi_opener: Optional[Callable[..., Any]] = None,
    openfigi_sleeper: Optional[Callable[[float], None]] = None,
) -> Mapping[str, Any]:
    """Refresh the UK universe from FIRDS, then enrich tickers via OpenFIGI.

    The free OpenFIGI mapping API (anonymous, key-free at low volume) maps
    ISINs to tickers for UK equities. Enrichment is best-effort: a failure
    keeps any previously cached ticker mapping and never breaks the FIRDS
    cache. Set ``enrich_tickers=False`` or ``UK_UNIVERSE_ENRICH_TICKERS=false``
    to skip the network enrichment step.
    """
    cache_path = _cache_path(path)
    source_name = source or os.environ.get("UK_UNIVERSE_SOURCE", "firds")
    if source_name != "firds":
        raise UkUniverseError(f"Unknown UK universe source: {source_name}")

    files = _latest_fulins_files()
    if not files:
        raise UkUniverseError(
            "FCA FIRDS returned no FULINS files for the latest date."
        )
    publication_date = _publication_date(files[0])
    if max_parts is not None:
        files = files[: max(1, int(max_parts))]

    entries: Dict[str, Mapping[str, Any]] = {}
    mic_seen = set()
    for index, file_source in enumerate(files):
        file_name = str(file_source["file_name"])
        LOGGER.info(
            "uk_universe downloading %s (%d/%d)",
            file_name,
            index + 1,
            len(files),
        )
        payload = _download_bytes(FIRDS_FILE_PREFIX + file_name)
        records, file_mics = _parse_zip_bytes(payload)
        mic_seen.update(file_mics)
        for record in records:
            isin = record["isin"]
            if isin in entries:
                continue
            entries[isin] = record
        if index < len(files) - 1:
            time.sleep(REQUEST_SLEEP_SECONDS)

    items = sorted(
        entries.values(),
        key=lambda item: (str(item.get("ticker") or ""), str(item["isin"])),
    )
    if enrich_tickers is None:
        raw_enrich = os.environ.get(
            "UK_UNIVERSE_ENRICH_TICKERS",
            "true",
        ).strip().lower()
        enrich_tickers = raw_enrich not in {"0", "false", "no", "off"}
    if enrich_tickers:
        previous = load_uk_universe(cache_path)
        previous_by_isin = {
            str(item.get("isin") or ""): item
            for item in (previous or {}).get("items") or []
        }
        mapping = _enrich_tickers_with_openfigi(
            items,
            opener=openfigi_opener or urlopen,
            sleeper=openfigi_sleeper or time.sleep,
        )
        for item in items:
            isin = str(item.get("isin") or "")
            if str(item.get("ticker") or ""):
                item["ticker_source"] = str(
                    item.get("ticker_source") or "seed"
                )
                continue
            new_ticker = mapping.get(isin)
            old_item = previous_by_isin.get(isin) or {}
            if not new_ticker:
                new_ticker = str(old_item.get("ticker") or "")
            if new_ticker:
                item["ticker"] = new_ticker
                item["ticker_source"] = (
                    "openfigi"
                    if isin in mapping
                    else str(old_item.get("ticker_source") or "previous")
                )
    payload = {
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "source": "firds",
        "publication_date": publication_date,
        "mic_seen": sorted(mic_seen),
        "items": items,
    }
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = cache_path.with_suffix(cache_path.suffix + ".tmp")
    with temporary_path.open("w", encoding="utf-8") as cache_file:
        json.dump(payload, cache_file, ensure_ascii=False)
    temporary_path.replace(cache_path)
    return payload


def search_uk_universe(
    query: str,
    path: Optional[Path] = None,
) -> List[Mapping[str, Any]]:
    """Search the cached UK universe by ticker or name substring."""
    payload = load_uk_universe(path)
    if not payload:
        return []
    needle = str(query or "").strip().lower()
    if not needle:
        return []
    matches: List[Mapping[str, Any]] = []
    for item in payload.get("items") or []:
        haystack = (
            f"{item.get('ticker') or ''} {item.get('name') or ''}"
        ).lower()
        if needle in haystack:
            matches.append(dict(item))
        if len(matches) >= 50:
            break
    return matches


def _enrich_tickers_with_openfigi(
    items: List[Mapping[str, Any]],
    *,
    opener: Callable[..., Any],
    sleeper: Callable[[float], None],
) -> Dict[str, str]:
    """Map ISIN -> ticker for ticker-less UK equities via OpenFIGI.

    Batches of 100 ISINs are posted to the free mapping endpoint with a
    polite sleep between batches. Any batch failure logs a warning and stops
    enrichment without raising; the caller keeps previous ticker data.
    """
    pending = [
        str(item["isin"])
        for item in items
        if str(item.get("instrument_kind") or "") == "equity"
        and str(item.get("ticker") or "") == ""
        and str(item.get("isin") or "")
    ]
    mapping: Dict[str, str] = {}
    for offset in range(0, len(pending), OPENFIGI_BATCH_SIZE):
        chunk = pending[offset : offset + OPENFIGI_BATCH_SIZE]
        body = json.dumps(
            [
                {
                    "idType": "ID_ISIN",
                    "idValue": isin,
                    "exchCode": "LN",
                }
                for isin in chunk
            ]
        ).encode("utf-8")
        request = Request(
            _openfigi_url(),
            data=body,
            headers={
                "User-Agent": "InvestmentMonitor/0.1 (internal workspace)",
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
            method="POST",
        )
        try:
            with opener(request, timeout=30) as response:
                raw = response.read()
            rows = json.loads(raw.decode("utf-8", errors="replace"))
            if not isinstance(rows, list):
                raise UkUniverseError(
                    "OpenFIGI mapping response was not a JSON list."
                )
            if len(rows) != len(chunk):
                LOGGER.warning(
                    "OpenFIGI returned %d rows for %d jobs; "
                    "skipping this batch",
                    len(rows),
                    len(chunk),
                )
                if offset + OPENFIGI_BATCH_SIZE < len(pending):
                    sleeper(OPENFIGI_REQUEST_SLEEP_SECONDS)
                continue
            for isin, row in zip(chunk, rows):
                if not isinstance(row, dict):
                    continue
                if "error" in row or "warning" in row:
                    continue
                data = row.get("data")
                if not isinstance(data, list):
                    continue
                ticker = _pick_openfigi_ticker(data)
                if ticker:
                    mapping[isin] = ticker
        except Exception as error:
            LOGGER.warning(
                "OpenFIGI ticker enrichment failed at offset %d: %s",
                offset,
                error,
            )
            break
        if offset + OPENFIGI_BATCH_SIZE < len(pending):
            sleeper(OPENFIGI_REQUEST_SLEEP_SECONDS)
    return mapping


def _pick_openfigi_ticker(data: List[Any]) -> str:
    """Prefer an LN/LSE listing, then the first entry with a ticker."""
    fallback: List[str] = []
    for entry in data:
        if not isinstance(entry, dict):
            continue
        ticker = str(entry.get("ticker") or "").strip()
        if not ticker:
            continue
        exchange = str(entry.get("exchCode") or "").upper()
        if exchange in {"LN", "LSE"}:
            return ticker
        fallback.append(ticker)
    return fallback[0] if fallback else ""


def _openfigi_url() -> str:
    return os.environ.get("UK_UNIVERSE_OPENFIGI_URL", OPENFIGI_MAPPING_URL)


def uk_universe_name_map(
    path: Optional[Path] = None,
) -> Mapping[str, Mapping[str, str]]:
    """Return ticker -> {name, exchange} for web add-company fallback."""
    payload = load_uk_universe(path)
    if not payload:
        return {}
    result: Dict[str, Mapping[str, str]] = {}
    for item in payload.get("items") or []:
        ticker = str(item.get("ticker") or "").strip()
        if not ticker:
            continue
        result[ticker] = {
            "name": str(item.get("name") or ""),
            "exchange": "LSE",
        }
    return result


def _latest_fulins_files() -> List[Mapping[str, Any]]:
    query = urlencode(
        {
            "q": "file_type:FULINS",
            "from": "0",
            "size": "200",
            "sort": "publication_date:desc",
        }
    )
    payload = _get_json(FIRDS_LIST_URL + "?" + query)
    hits = (payload.get("hits") or {}).get("hits") or []
    sources = [hit.get("_source") or {} for hit in hits if isinstance(hit, dict)]
    if not sources:
        return []
    latest = max(
        str(source.get("publication_date") or "")
        for source in sources
        if source.get("publication_date")
    )
    files = sorted(
        (
            source
            for source in sources
            if str(source.get("publication_date") or "") == latest
            and source.get("download_link")
            and source.get("file_name")
        ),
        key=lambda source: str(source["file_name"]),
    )
    return files


def _publication_date(source: Mapping[str, Any]) -> str:
    return str(source.get("publication_date") or "")


def _parse_zip_bytes(data: bytes) -> tuple:
    """Return (uk-filtered records, set of MICs seen in the file)."""
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            xml_name = next(
                name for name in archive.namelist() if name.endswith(".xml")
            )
            with archive.open(xml_name) as xml_file:
                records, mic_seen = _parse_xml_records(xml_file)
    except (zipfile.BadZipFile, KeyError, StopIteration) as error:
        raise UkUniverseError(
            "FCA FIRDS file is not a valid instrument ZIP."
        ) from error
    return records, mic_seen


def _parse_xml_records(xml_stream: Any) -> tuple:
    records: List[Mapping[str, Any]] = []
    mic_seen = set()
    for _event, element in ElementTree.iterparse(
        xml_stream,
        events=("end",),
    ):
        local = str(element.tag).split("}")[-1]
        if local != "RefData":
            continue
        record = _record_from_element(element)
        element.clear()
        if record is None:
            continue
        venues = record["venues"]
        mic_seen.update(venues)
        if not any(_is_uk_venue(venue) for venue in venues):
            continue
        isin = record["isin"]
        ticker = next(
            (
                seed_ticker
                for seed_ticker, seed_isin in TICKER_ISIN_SEED.items()
                if seed_isin == isin
            ),
            "",
        )
        records.append(
            {
                "ticker": ticker,
                "ticker_source": "seed" if ticker else "",
                "name": record["name"],
                "isin": isin,
                "lei": record["lei"],
                "exchange": "LSE",
                "mic": venues,
                "instrument_kind": _instrument_kind(record["cfi"]),
            }
        )
    return records, mic_seen


def _record_from_element(element: Any) -> Optional[Mapping[str, Any]]:
    general = _local_child(element, "FinInstrmGnlAttrbts")
    if general is None:
        return None
    isin = _child_text(general, "Id")
    name = _child_text(general, "FullNm")
    if not isin or not name:
        return None
    cfi = _child_text(general, "ClssfctnTp")
    lei = _child_text(element, "Issr")
    tech = _local_child(element, "TechAttrbts")
    venues = []
    if tech is not None:
        for child in tech.iter():
            if str(child.tag).split("}")[-1] == "RlvntTradgVn" and child.text:
                value = child.text.strip().upper()
                if value and value not in venues:
                    venues.append(value)
    return {
        "isin": isin.strip().upper(),
        "name": name.strip(),
        "lei": (lei or "").strip().upper(),
        "cfi": (cfi or "").strip().upper(),
        "venues": venues,
    }


def _local_child(element: Any, local_name: str) -> Optional[Any]:
    for child in element:
        if str(child.tag).split("}")[-1] == local_name:
            return child
    return None


def _child_text(element: Any, local_name: str) -> str:
    child = _local_child(element, local_name)
    return child.text or "" if child is not None else ""


def _is_uk_venue(venue: str) -> bool:
    return venue in UK_VENUE_MICS or venue.startswith("AIM")


def _instrument_kind(cfi: str) -> str:
    if cfi.startswith("ET"):
        return "etf"
    if cfi.startswith("E"):
        return "equity"
    return "other"


def _get_json(url: str) -> Any:
    request = Request(
        url,
        headers={
            "User-Agent": "InvestmentMonitor/0.1 (internal workspace)",
            "Accept": "application/json",
        },
    )
    with urlopen(request, timeout=60) as response:
        return json.loads(response.read().decode("utf-8"))


def _download_bytes(url: str) -> bytes:
    request = Request(
        url,
        headers={
            "User-Agent": "InvestmentMonitor/0.1 (internal workspace)",
        },
    )
    with urlopen(request, timeout=600) as response:
        return response.read()


def _cache_path(path: Optional[Path]) -> Path:
    return Path(
        path or os.environ.get("UK_UNIVERSE_CACHE_PATH", DEFAULT_CACHE_PATH)
    )
