"""Pure parsing for the ``TICKER.MARKET`` / ``TICKER@MARKET`` mixed batch format.

The Lists & sources page lets a user paste many symbols at once, each
optionally carrying a market/exchange suffix (``AAPL.US``, ``0700.HK``,
``RY.TO``, or the ``@`` form ``0700@HK``). This module only splits and
classifies that raw text into per-token ``(ticker, market)`` pairs; it has no
HTTP, SQLite, resolver, collection, environment, or network dependency, so the
rules stay testable and the web layer stays the sole place where HTTP payloads
and persistence meet.

Two separators are accepted between the ticker and its market suffix:

* ``@`` is the preferred separator (``0700@HK``) because ``@`` never appears
  inside a real ticker, so it can never be ambiguous.
* ``.`` remains supported for backwards compatibility (``0700.HK``). When both
  appear, ``@`` wins (``BRK.B@US`` is ticker ``BRK.B`` in market ``us``).

Key rule — never corrupt a ticker that merely contains a dot: only the text
after the *last* separator is treated as a candidate suffix, and only when it
is in the explicit suffix/alias allowlist below. ``BRK.B`` keeps the ``.B``
inside the ticker and never becomes ``BRK`` in a market named ``b``.
"""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Dict, List, Optional, Sequence, Tuple

# Canonical internal market codes, also accepted verbatim as import suffixes.
# ``unknown`` is deliberately absent: it is an internal state, not a suffix a
# user should type.
_CANONICAL_SUFFIXES: Dict[str, str] = {
    "us": "us",
    "cn": "cn",
    "hk": "hk",
    "jp": "jp",
    "kr": "kr",
    "uk": "uk",
    "tw": "tw",
    "ca": "ca",
    "au": "au",
    "be": "be",
    "fr": "fr",
    "de": "de",
    "nl": "nl",
    "it": "it",
    "es": "es",
    "sg": "sg",
    "ch": "ch",
    "pl": "pl",
    "se": "se",
    "aq": "aq",
    "cxe": "cxe",
    "emf": "emf",
    "trq": "trq",
    "eux": "eux",
    "ee": "ee",
    "lv": "lv",
    "lt": "lt",
    "no": "no",
    "pt": "pt",
    "at": "at",
}

# Common exchange / quote suffix aliases, mapped to a canonical market. This is
# a static, auditable table; nothing here is guessed over the network.
_EXCHANGE_ALIASES: Dict[str, str] = {
    # Canada
    "to": "ca",
    "tsx": "ca",
    "v": "ca",
    "cnx": "ca",
    # Australia
    "ax": "au",
    # United Kingdom
    "l": "uk",
    "lse": "uk",
    # South Korea
    "ks": "kr",
    "kq": "kr",
    "kospi": "kr",
    "kosdaq": "kr",
    # Japan
    "t": "jp",
    # China (A-shares)
    "ss": "cn",
    "sz": "cn",
    "sh": "cn",
    # Spain
    "mc": "es",
    "bme": "es",
    # Switzerland
    "sw": "ch",
    "six": "ch",
    # Singapore
    "si": "sg",
    "sgx": "sg",
    # Poland
    "wa": "pl",
    # Baltic (Nasdaq Tallinn / Riga / Vilnius quote suffixes)
    "tl": "ee",
    "rg": "lv",
    "vl": "lt",
    # Norway / Portugal (Oslo Bors / Euronext Lisbon quote suffixes)
    "ol": "no",
    "ls": "pt",
    # Austria (Vienna Stock Exchange quote suffix)
    "vi": "at",
    "wse": "pl",
    "gpw": "pl",
    # Sweden
    "st": "se",
    "sto": "se",
    "omx": "se",
    # France
    "pa": "fr",
    # Belgium
    "br": "be",
    # Netherlands
    "as": "nl",
    # Italy
    "mi": "it",
    "mil": "it",
    "bit": "it",
    # Germany
    "f": "de",
    "etr": "de",
    "xetra": "de",
    # Aquis
    "aqse": "aq",
    # Cboe Europe
    "bxe": "cxe",
    # Turquoise
    "trqx": "trq",
    "tqex": "trq",
}

# Suffix (lowercased) -> canonical market. The canonical table wins over the
# alias table on any overlap (none today), which keeps the mapping explicit.
SUFFIX_TO_MARKET: Dict[str, str] = {**_EXCHANGE_ALIASES, **_CANONICAL_SUFFIXES}

# Whitespace, newline, comma, semicolon, full-width comma/semicolon.
_TOKEN_SPLIT_RE = re.compile(r"[,\s;，；]+")


@dataclass(frozen=True)
class ParsedCompanyInput:
    """One import token resolved to a canonical (ticker, market) pair."""

    raw_token: str
    ticker: str
    market: str
    explicit_suffix: Optional[str] = None


def split_tokens(raw_text: str) -> List[str]:
    """Split raw input on every supported separator, dropping empty pieces."""
    if not raw_text:
        return []
    return [token for token in _TOKEN_SPLIT_RE.split(raw_text) if token]


def _candidate_suffix(text: str) -> Tuple[str, Optional[str]]:
    """Split one token into ``(ticker_part, candidate_suffix)``.

    ``@`` is checked first and is therefore the preferred market separator
    (``0700@HK``); ``.`` is the fallback (``0700.HK``). Only the text after the
    *last* separator is a candidate suffix, and only when the text before it is
    non-empty — so a leading separator (``.US`` / ``@HK``) keeps the whole
    token intact. The returned suffix is lowercased; the caller decides whether
    it is in the allowlist.
    """
    ticker = text.strip()
    for separator in ("@", "."):
        if separator in ticker:
            head, suffix = ticker.rsplit(separator, 1)
            if head.strip():
                return head.strip(), suffix.lower()
            return ticker, None
    return ticker, None


def market_for_suffix(suffix: str) -> Optional[str]:
    """Return the canonical market for a suffix, or None if not recognized."""
    return SUFFIX_TO_MARKET.get(suffix.strip().lower())


def parse_company_inputs(
    raw_text: str,
    default_market: str,
) -> List[ParsedCompanyInput]:
    """Parse mixed batch input into ordered, de-duplicated (ticker, market) items.

    Rules, in order:

    1. Split on whitespace / newline / comma / semicolon (and their full-width
       forms).
    2. For each token, only the part after the *last* ``@`` (or, when there is
       no ``@``, the last ``.``) is a candidate suffix. If it is in
       ``SUFFIX_TO_MARKET`` (case-insensitive) it selects that market and the
       remainder becomes the ticker.
    3. Otherwise the whole token is the ticker and ``default_market`` applies
       (so ``BRK.B`` stays ``BRK.B`` in the selected market).
    4. De-duplicate by ``(ticker.upper(), market)``, preserving first-seen
       order. ``ABC.US`` and ``ABC.HK`` remain two distinct entries, and
       ``ABC@US`` de-duplicates against ``ABC.US`` (same ticker + market).
    """
    parsed: List[ParsedCompanyInput] = []
    seen = set()
    for token in split_tokens(raw_text):
        ticker = token.strip()
        market = default_market
        explicit_suffix: Optional[str] = None
        head, suffix = _candidate_suffix(ticker)
        if suffix is not None:
            canonical = SUFFIX_TO_MARKET.get(suffix)
            if canonical is not None:
                ticker = head
                market = canonical
                explicit_suffix = suffix
        key = (ticker.upper(), market)
        if key in seen:
            continue
        seen.add(key)
        parsed.append(
            ParsedCompanyInput(
                raw_token=token,
                ticker=ticker,
                market=market,
                explicit_suffix=explicit_suffix,
            )
        )
    return parsed


def group_by_market(
    parsed: Sequence[ParsedCompanyInput],
) -> List[Tuple[str, List[ParsedCompanyInput]]]:
    """Group parsed inputs by canonical market, preserving first-seen order."""
    order: List[str] = []
    buckets: Dict[str, List[ParsedCompanyInput]] = {}
    for item in parsed:
        if item.market not in buckets:
            buckets[item.market] = []
            order.append(item.market)
        buckets[item.market].append(item)
    return [(market, buckets[market]) for market in order]

