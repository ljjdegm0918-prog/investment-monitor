"""Universe-backed company matching for AMF OAM records.

The AMF OAM feed identifies issuers by company name
(``societes[].raisonSociale``), never by ticker mnemonic. To avoid fake
matches, a record is matched against the FR universe cache identity for
the requested ticker: the cache company name (normalized) and the cache
ISIN. The ticker mnemonic itself is never used as a name pattern.
"""

from __future__ import annotations

import re
import unicodedata
from typing import Any, Iterable, Mapping

# Legal-form / corporate-status tokens that are stripped from both sides of
# a name comparison so "LVMH MOET HENNESSY LOUIS VUITTON SE" aligns with
# "LVMH MOET HENNESSY LOUIS VUITTON". Tokens are matched at the end of the
# normalized name only, and a suffix is dropped only when enough name
# remains (never reducing a name to nothing).
_LEGAL_FORM_SUFFIXES = (
    "SOCIETE ANONYME",
    "SOCIETE PAR ACTIONS SIMPLIFIEE",
    "SOCIETE EN COMMANDITE PAR ACTIONS",
    "SOCIETAS EUROPAEA",
    "S A",
    "S A S",
    "S C A",
    "SA",
    "SAS",
    "SCA",
    "SASU",
    "SNC",
    "SE",
    "GROUPE",
)
_LEGAL_FORM_PATTERN = re.compile(
    r"(?:\s+(?:" + "|".join(
        re.escape(suffix) for suffix in _LEGAL_FORM_SUFFIXES
    ) + r"))+$"
)


def normalize_company_name(value: Any) -> str:
    """Normalize a company name for lossy side-by-side comparison.

    Strips accents and legal-form suffixes, uppercases, and collapses all
    punctuation and whitespace (``L'Oreal`` -> ``LOREAL``, ``S.A.`` ->
    ``SA``). The result is a bare ASCII token string.
    """
    text = unicodedata.normalize("NFKD", str(value or ""))
    text = "".join(
        char for char in text if not unicodedata.combining(char)
    )
    text = text.upper()
    text = re.sub(r"[^A-Z0-9]+", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    while True:
        stripped = _LEGAL_FORM_PATTERN.sub("", text).strip()
        if stripped == text or len(stripped) < 3:
            break
        text = stripped
    return text


def company_names_match(universe_name: Any, record_name: Any) -> bool:
    """True when a universe name and a payload company name align.

    Exact equality wins; otherwise a longer name is allowed to contain the
    other (both directions) so official vs. abbreviated spellings still
    match. Short fragments (under five characters) never match by
    containment, which keeps ``AI`` (Air Liquide) from colliding with
    unrelated names.
    """
    left = normalize_company_name(universe_name)
    right = normalize_company_name(record_name)
    if not left or not right or len(left) < 3 or len(right) < 3:
        return False
    if left == right:
        return True
    if len(left) >= 5 and left in right:
        return True
    if len(right) >= 5 and right in left:
        return True
    return False


def _iter_texts(value: Any) -> Iterable[str]:
    """Yield every string leaf in a nested record structure."""
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for child in value.values():
            yield from _iter_texts(child)
    elif isinstance(value, (list, tuple)):
        for child in value:
            yield from _iter_texts(child)


def record_has_isin(record: Mapping[str, Any], isin: Any) -> bool:
    """True when an ISIN appears in any string field of a raw record."""
    needle = str(isin or "").strip().upper()
    if not needle:
        return False
    return any(needle in str(text).upper() for text in _iter_texts(record))


class AmfOamCompanyMatcher:
    """Match parsed AMF OAM records against a universe identity.

    An identity is the FR universe cache entry for a requested ticker
    (company name and/or ISIN). The ticker is never part of the pattern.
    """

    def matches(
        self,
        record: Mapping[str, Any],
        *,
        name: str,
        isin: str,
    ) -> bool:
        companies = record.get("companies") or ()
        if name:
            if any(
                company_names_match(name, company_name)
                for company_name in companies
            ):
                return True
        if isin:
            raw = record.get("raw")
            if record_has_isin(raw if isinstance(raw, dict) else record, isin):
                return True
        return False
