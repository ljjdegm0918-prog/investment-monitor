# -*- coding: utf-8 -*-
"""Official Budapest Stock Exchange (BSE/BET) Hungarian equity universe.

The public BSE issuer directory embeds its complete ``IssuerDataSource`` in
the server-rendered HTML.  That directory is only a candidate list: an
issuer may also have bonds, funds, or certificates.  A refresh therefore
reads each HU Prime/Standard/Xtend candidate's official issuer profile and
then the public security profile for every listed security.  Only securities
whose own official fields say ``Equity class`` and a recognised equity market
are retained.

This is an official BSE scope, not a claim about every Hungarian venue,
delisted security, or historical issuer.  Refreshes are deliberately
fail-closed and atomically replace the cache only after at least one profile
has been completely validated.
"""

from __future__ import annotations

import html
import json
import os
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Mapping, Optional, Sequence
from urllib.parse import quote

from ..sources._public_disclosure import clean_html, company_key, fetch_text
from ..web_repository import normalize_hu_ticker

DEFAULT_CACHE_PATH = ".cache/investment_monitor/hu_universe.json"
DIRECTORY_URL = "https://www.bse.hu/site/Angol/pages/issuers"
ISSUER_PROFILE_TEMPLATE = "https://www.bse.hu/pages/company_profile/$issuer/{issuer_id}"
SECURITY_PROFILE_TEMPLATE = "https://www.bse.hu/pages/company_profile/$security/{ticker}"

# These are the observed BSE issuer-directory group IDs, not name heuristics.
EQUITY_GROUP_IDS = frozenset({"W_RESZVENYA", "W_RESZVENYB", "W_SME"})
EQUITY_MARKETS = frozenset({"Prime", "Standard", "Xtend"})
EQUITY_CLASSES = frozenset({"Ordinary share", "Preferred share"})
MIN_DIRECTORY_ISSUERS = 100
MIN_EQUITY_CANDIDATES = 25
_ISIN_PATTERN = re.compile(r"HU[0-9A-Z]{10}")


class HuUniverseError(RuntimeError):
    """Raised when the official HU universe cannot be safely refreshed."""


def _cache_path(path: Optional[Path]) -> Path:
    return Path(path or os.environ.get("HU_UNIVERSE_CACHE_PATH", DEFAULT_CACHE_PATH))


def load_hu_universe(path: Optional[Path] = None) -> Optional[Mapping[str, Any]]:
    """Load a cached HU universe, returning ``None`` for absent/bad caches."""
    cache_file = _cache_path(path)
    try:
        with cache_file.open(encoding="utf-8") as handle:
            payload = json.load(handle)
    except (OSError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, Mapping) else None


def parse_hu_issuer_directory(
    text: str,
    *,
    minimum_issuers: int = MIN_DIRECTORY_ISSUERS,
    minimum_candidates: int = MIN_EQUITY_CANDIDATES,
) -> Sequence[Mapping[str, Any]]:
    """Return valid HU equity-group issuer candidates from BSE's inline JSON.

    The BSE page contains a visible sign-in component even for anonymous,
    public data.  It is *not* treated as an access failure; the required
    embedded ``IssuerDataSource`` is the actual public-data contract.
    """
    if not isinstance(text, str) or not text.strip():
        raise HuUniverseError("BSE issuer directory returned no HTML")
    match = re.search(
        r"window\.dataSourceResults\s*=\s*(\{.*?\})\s*</script>",
        text,
        flags=re.S,
    )
    if not match:
        raise HuUniverseError("BSE issuer directory is missing IssuerDataSource")
    try:
        payload = json.loads(match.group(1))
    except json.JSONDecodeError as error:
        raise HuUniverseError("BSE IssuerDataSource is not valid JSON") from error
    issuers = payload.get("IssuerDataSource") if isinstance(payload, Mapping) else None
    if not isinstance(issuers, list):
        raise HuUniverseError("BSE IssuerDataSource is missing or not a list")
    if len(issuers) < minimum_issuers:
        raise HuUniverseError(
            f"BSE issuer directory is suspiciously small: {len(issuers)} < {minimum_issuers}"
        )

    candidates: List[Mapping[str, Any]] = []
    issuer_ids: set[int] = set()
    for raw in issuers:
        if not isinstance(raw, Mapping):
            raise HuUniverseError("BSE IssuerDataSource contains a non-object issuer")
        country = str(raw.get("country") or "").strip()
        try:
            issuer_id = int(raw["issuerid"])
        except (KeyError, TypeError, ValueError) as error:
            raise HuUniverseError("BSE issuer is missing a valid issuerid") from error
        groups = raw.get("instrumentumGroups")
        if not isinstance(groups, list):
            raise HuUniverseError("BSE issuer is missing instrumentumGroups")
        group_ids = []
        for group in groups:
            if not isinstance(group, Mapping):
                raise HuUniverseError("BSE issuer has an invalid instrumentum group")
            group_id = str(group.get("id") or "").strip()
            if not group_id:
                raise HuUniverseError("BSE issuer group is missing its id")
            group_ids.append(group_id)
        if country != "HU" or not set(group_ids).intersection(EQUITY_GROUP_IDS):
            continue
        if issuer_id in issuer_ids:
            raise HuUniverseError(f"BSE issuer directory repeats issuerid {issuer_id}")
        issuer_ids.add(issuer_id)
        identity_names = tuple(
            dict.fromkeys(
                value
                for value in (
                    str(raw.get("shortNameEng") or "").strip(),
                    str(raw.get("shortName") or "").strip(),
                )
                if value
            )
        )
        name = identity_names[0] if identity_names else ""
        if not name:
            raise HuUniverseError(f"BSE issuer {issuer_id} has no name")
        candidates.append(
            {
                "issuer_id": issuer_id,
                "name": name,
                "identity_names": identity_names,
                "country": country,
                "instrumentum_groups": sorted(group_ids),
            }
        )
    if len(candidates) < minimum_candidates:
        raise HuUniverseError(
            "BSE HU equity candidate count is suspiciously small: "
            f"{len(candidates)} < {minimum_candidates}"
        )
    return tuple(candidates)


def parse_hu_issuer_profile(text: str) -> Sequence[Mapping[str, str]]:
    """Parse an issuer profile's listed-security rows without classifying them."""
    if not isinstance(text, str) or "Listed securities of the issuer" not in text:
        raise HuUniverseError("BSE issuer profile is missing listed securities")
    _parse_hu_profile_issuer_name(text)
    table_match = re.search(
        r"<table\b[^>]*class=[\"'][^\"']*table_ertekpapirok[^\"']*[\"'][^>]*>(.*?)</table>",
        text,
        flags=re.I | re.S,
    )
    if not table_match:
        raise HuUniverseError("BSE issuer profile securities table is missing")
    table = table_match.group(1)
    headers = tuple(
        clean_html(cell)
        for cell in re.findall(r"<th\b[^>]*>(.*?)</th>", table, flags=re.I | re.S)
    )
    if headers != ("Name", "Ticker", "ISIN"):
        raise HuUniverseError(f"BSE issuer profile columns changed: {headers!r}")
    rows: List[Mapping[str, str]] = []
    for row in re.findall(r"<tr\b[^>]*>(.*?)</tr>", table, flags=re.I | re.S):
        cells = re.findall(r"<td\b[^>]*>(.*?)</td>", row, flags=re.I | re.S)
        if not cells:
            continue
        if len(cells) != 3:
            raise HuUniverseError("BSE issuer profile row column count changed")
        ticker_match = re.search(
            r"loadSecurity\(&#39;([^&]+?)&#39;\)", cells[0], flags=re.I
        )
        if not ticker_match:
            raise HuUniverseError("BSE issuer profile row is missing security link")
        name, ticker_cell, isin = (clean_html(cell) for cell in cells)
        ticker = html.unescape(ticker_match.group(1)).strip().upper()
        if not name or not ticker or ticker != ticker_cell.strip().upper():
            raise HuUniverseError("BSE issuer profile security identity is inconsistent")
        if not _ISIN_PATTERN.fullmatch(isin):
            raise HuUniverseError(f"BSE issuer profile has invalid ISIN {isin!r}")
        rows.append({"security_name": name, "ticker": ticker, "isin": isin})
    if not rows:
        raise HuUniverseError("BSE issuer profile has no listed security rows")
    return tuple(rows)


def _parse_hu_profile_issuer_name(text: str) -> str:
    """Return the profile's own issuer name (English when BSE publishes it)."""
    for element_id in ("issuerNameEn", "issuerName"):
        match = re.search(
            rf'<div\b[^>]*id=["\']{element_id}["\'][^>]*>(.*?)</div>',
            text,
            flags=re.I | re.S,
        )
        if match:
            name = clean_html(match.group(1))
            if name:
                return str(name)
    raise HuUniverseError("BSE issuer profile is missing its issuer name")


def parse_hu_security_profile(text: str) -> Mapping[str, str]:
    """Read authoritative identity and equity classification from one security page."""
    if not isinstance(text, str) or not text.strip():
        raise HuUniverseError("BSE security profile returned no HTML")
    pairs = {
        clean_html(label): clean_html(value)
        for label, value in re.findall(
            r"<tr>\s*<td>(.*?)</td>\s*<td>(.*?)</td>\s*</tr>",
            text,
            flags=re.I | re.S,
        )
    }
    # Bond profiles legitimately omit both ``Equity class`` and ``Market``.
    # Those omissions make the security ineligible, rather than turning a
    # mixed issuer (for example 4iG shares plus bonds) into a failed issuer.
    required = ("Name of security", "Code of security (ISIN)", "Ticker symbol")
    if any(not pairs.get(label) for label in required):
        raise HuUniverseError("BSE security profile is missing required identity fields")
    isin = pairs["Code of security (ISIN)"].upper()
    ticker = pairs["Ticker symbol"].upper()
    if not _ISIN_PATTERN.fullmatch(isin) or not normalize_hu_ticker(ticker):
        raise HuUniverseError("BSE security profile has invalid ticker or ISIN")
    return {
        "security_name": pairs["Name of security"],
        "equity_class": pairs.get("Equity class", ""),
        "isin": isin,
        "ticker": ticker,
        "market": pairs.get("Market", ""),
    }


def refresh_hu_universe(
    *,
    path: Optional[Path] = None,
    fetcher: Callable[[str], Any] = fetch_text,
    directory_url: str = DIRECTORY_URL,
    issuer_profile_template: str = ISSUER_PROFILE_TEMPLATE,
    security_profile_template: str = SECURITY_PROFILE_TEMPLATE,
    refreshed_at: Optional[str] = None,
    requests_per_second: float = 0.5,
    sleeper: Callable[[float], None] = time.sleep,
    minimum_issuers: int = MIN_DIRECTORY_ISSUERS,
    minimum_candidates: int = MIN_EQUITY_CANDIDATES,
) -> Mapping[str, Any]:
    """Refresh the BSE HU equity universe with bounded, serial public reads.

    ``fetch_text`` already retries transient HTTP/network failures.  Profile
    failures are recorded per issuer and yield a partial cache if other
    profiles validate.  Directory failures, identity conflicts, and zero
    successful profiles raise before the previous cache can be replaced.
    """
    if requests_per_second <= 0:
        raise ValueError("requests_per_second must be positive")
    try:
        directory_html = _text_from_fetcher(fetcher, directory_url)
        candidates = parse_hu_issuer_directory(
            directory_html,
            minimum_issuers=minimum_issuers,
            minimum_candidates=minimum_candidates,
        )
    except Exception as error:
        if isinstance(error, HuUniverseError):
            raise
        raise HuUniverseError(f"BSE issuer directory failed: {error}") from error

    entries: List[Mapping[str, Any]] = []
    failures: List[Mapping[str, Any]] = []
    seen_tickers: Dict[str, str] = {}
    seen_isins: Dict[str, str] = {}
    interval = 1.0 / requests_per_second
    last_request_at: Optional[float] = None

    def read(url: str) -> str:
        nonlocal last_request_at
        if last_request_at is not None:
            remaining = interval - (time.monotonic() - last_request_at)
            if remaining > 0:
                sleeper(remaining)
        try:
            return _text_from_fetcher(fetcher, url)
        finally:
            last_request_at = time.monotonic()

    for candidate in candidates:
        issuer_id = int(candidate["issuer_id"])
        issuer_url = issuer_profile_template.format(issuer_id=issuer_id)
        try:
            profile_html = read(issuer_url)
            issuer_name = _parse_hu_profile_issuer_name(profile_html)
            profile_key = company_key(issuer_name)
            candidate_keys = {
                company_key(str(value))
                for value in candidate.get("identity_names") or (candidate["name"],)
            }
            if not profile_key or profile_key not in candidate_keys:
                raise HuUniverseError(
                    "BSE issuer profile identity does not match directory candidate: "
                    f"issuer_id={issuer_id} directory={candidate['name']!r} "
                    f"profile={issuer_name!r}"
                )
            securities = parse_hu_issuer_profile(profile_html)
            validated = []
            candidate_equity_groups = set(candidate["instrumentum_groups"]).intersection(
                EQUITY_GROUP_IDS
            )
            for listed in securities:
                ticker = str(listed["ticker"])
                security_url = security_profile_template.format(ticker=quote(ticker, safe=""))
                detail = parse_hu_security_profile(read(security_url))
                if detail["ticker"] != ticker or detail["isin"] != listed["isin"]:
                    raise HuUniverseError(
                        f"BSE security identity conflicts for issuer {issuer_id}: {ticker}"
                    )
                market = detail["market"]
                # Current Xtend security profiles omit the Market row even
                # though the official issuer directory classifies the issuer
                # solely as W_SME (Equities Xtend).  Use that official group
                # only when it is the unique equity-group evidence; mixed
                # groups remain ambiguous and are never guessed.
                if not market and candidate_equity_groups == {"W_SME"}:
                    market = "Xtend"
                if detail["equity_class"] not in EQUITY_CLASSES or market not in EQUITY_MARKETS:
                    continue
                normalized = normalize_hu_ticker(ticker)
                if not normalized:
                    raise HuUniverseError(f"BSE security has unusable ticker {ticker!r}")
                validated.append(
                    {
                        "ticker": normalized,
                        "isin": detail["isin"],
                        "name": issuer_name,
                        "security_name": detail["security_name"],
                        "issuer_id": issuer_id,
                        "country": "HU",
                        "exchange": "Budapest Stock Exchange",
                        "board": market,
                        "market": market,
                        "equity_class": detail["equity_class"],
                        "issuer_profile_url": issuer_url,
                        "security_profile_url": security_url,
                        "source": "bse_official_issuer_and_security_profiles",
                        "aliases": [],
                    }
                )
            if not validated:
                raise HuUniverseError("BSE issuer profile had no validated equity security")
            for entry in validated:
                ticker = str(entry["ticker"])
                isin = str(entry["isin"])
                if ticker in seen_tickers or isin in seen_isins:
                    raise HuUniverseError(
                        "BSE equity identity conflict: "
                        f"ticker={ticker} isin={isin}"
                    )
                seen_tickers[ticker] = isin
                seen_isins[isin] = ticker
                entries.append(entry)
        except Exception as error:
            # Conflicts indicate incorrect identity, not an ordinary transient
            # per-profile failure.  Never publish a potentially mixed universe.
            if isinstance(error, HuUniverseError) and "identity conflict" in str(error):
                raise
            failures.append(
                {
                    "issuer_id": issuer_id,
                    "issuer_name": str(candidate["name"]),
                    "profile_url": issuer_url,
                    "error": str(error) or error.__class__.__name__,
                }
            )

    if not entries:
        raise HuUniverseError("BSE all candidate issuer profiles failed; cache preserved")
    counts: Dict[str, int] = {}
    for cached_entry in entries:
        board = str(cached_entry["board"])
        counts[board] = counts.get(board, 0) + 1
    payload = {
        "updated_at": refreshed_at or datetime.now(timezone.utc).isoformat(),
        "source": ["bse_official_issuer_directory", "bse_official_security_profiles"],
        "coverage": "official_bse_hungarian_prime_standard_xtend_equities_partial",
        "status": "partial" if failures else "success",
        "counts": {
            "directory_issuers": len(_issuer_rows_from_directory(directory_html)),
            "equity_candidate_issuers": len(candidates),
            "successful_issuers": len({int(entry["issuer_id"]) for entry in entries}),
            "failed_issuers": len(failures),
            "equities": len(entries),
            "by_board": counts,
        },
        "failures": failures,
        "items": sorted(entries, key=lambda item: (str(item["ticker"]), str(item["isin"]))),
    }
    cache_path = _cache_path(path)
    existing = load_hu_universe(cache_path)
    existing_items = existing.get("items") if isinstance(existing, Mapping) else None
    # A transient failure affecting one or more issuer profiles must not
    # replace a previously validated snapshot with a narrower partial one.
    # On a cold start, the partial result is still useful and is written with
    # its explicit failure audit; on a warm cache, return the run report while
    # preserving the last complete/better snapshot used by name fallback.
    if failures and isinstance(existing_items, list) and existing_items:
        payload["cache_write_status"] = "preserved_existing_cache_after_partial_refresh"
    else:
        payload["cache_write_status"] = "replaced_atomically"
        _write_cache_atomically(cache_path, payload)
    return payload


def hu_universe_name_map(path: Optional[Path] = None) -> Mapping[str, Mapping[str, str]]:
    """Return normalized ticker/ISIN -> official issuer identity."""
    payload = load_hu_universe(path)
    if not payload:
        return {}
    result: Dict[str, Mapping[str, str]] = {}
    for item in payload.get("items") or []:
        if not isinstance(item, Mapping):
            continue
        ticker = normalize_hu_ticker(str(item.get("ticker") or ""))
        isin = str(item.get("isin") or "").strip().upper()
        if not ticker or not _ISIN_PATTERN.fullmatch(isin):
            continue
        identity = {
            "name": str(item.get("name") or ticker),
            "exchange": str(item.get("exchange") or "Budapest Stock Exchange"),
            "board": str(item.get("board") or "BSE"),
            "isin": isin,
        }
        for key in (ticker, isin):
            existing = result.get(key)
            if existing and existing != identity:
                raise HuUniverseError(f"HU universe cache has conflicting key {key}")
            result[key] = identity
    return result


def search_hu_universe(query: str, path: Optional[Path] = None) -> List[Mapping[str, Any]]:
    """Search the cached HU universe by ticker, name, ISIN, or board."""
    payload = load_hu_universe(path)
    if not payload:
        return []
    needle = str(query or "").strip().casefold()
    if not needle:
        return []
    matches: List[Mapping[str, Any]] = []
    for item in payload.get("items") or []:
        if not isinstance(item, Mapping):
            continue
        haystack = " ".join(
            str(item.get(field) or "")
            for field in ("ticker", "name", "security_name", "isin", "board")
        ).casefold()
        if needle in haystack:
            matches.append(dict(item))
        if len(matches) >= 50:
            break
    return matches


def _issuer_rows_from_directory(text: str) -> Sequence[Any]:
    """Read only the raw count after the directory has already validated."""
    match = re.search(r"window\.dataSourceResults\s*=\s*(\{.*?\})\s*</script>", text, re.S)
    if not match:  # Defensive; parse_hu_issuer_directory already checked this.
        raise HuUniverseError("BSE issuer directory disappeared during parsing")
    payload = json.loads(match.group(1))
    issuers = payload.get("IssuerDataSource") if isinstance(payload, Mapping) else None
    if not isinstance(issuers, list):
        raise HuUniverseError("BSE issuer directory count is invalid")
    return issuers


def _text_from_fetcher(fetcher: Callable[[str], Any], url: str) -> str:
    response = fetcher(url)
    text = response[0] if isinstance(response, tuple) else response
    if not isinstance(text, str):
        raise HuUniverseError(f"BSE fetcher returned non-text response for {url}")
    return text


def _write_cache_atomically(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False)
    temporary.replace(path)


__all__ = [
    "DEFAULT_CACHE_PATH",
    "DIRECTORY_URL",
    "EQUITY_GROUP_IDS",
    "HuUniverseError",
    "ISSUER_PROFILE_TEMPLATE",
    "SECURITY_PROFILE_TEMPLATE",
    "hu_universe_name_map",
    "load_hu_universe",
    "parse_hu_issuer_directory",
    "parse_hu_issuer_profile",
    "parse_hu_security_profile",
    "refresh_hu_universe",
    "search_hu_universe",
]
