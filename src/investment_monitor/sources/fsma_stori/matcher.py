"""Universe-backed company matching for FSMA STORI records.

The STORI feed identifies issuers by their official FSMA abbreviation
(``companyName``, e.g. ``AB INBEV``) and by their ``isinCodes`` - never by
ticker mnemonic. To avoid fake matches (the French ``MC != LVMH`` trap
applies the same way to Belgium: ``ABI != Anheuser-Busch InBev``), a record
is matched against the universe identity for the requested ticker: the
universe company name (normalized, both directions) and the universe ISIN
(exact membership in the record's ``isinCodes``, with a raw-field scan as a
fallback). The ticker mnemonic itself is never used as a name pattern.
"""

from __future__ import annotations

import re
import unicodedata
from typing import Any, Iterable, Mapping

# Legal-form / corporate-status tokens stripped from both sides of a name
# comparison so "ANHEUSER-BUSCH INBEV SA/NV" aligns with "AB INBEV". The
# list covers the French and Dutch Belgian legal forms plus the common
# cross-border ones. Tokens are matched at the end of the normalized name
# only, and a suffix is dropped only when enough name remains.
_LEGAL_FORM_SUFFIXES = (
    "SOCIETE ANONYME",
    "SOCIETE PRIVEE A RESPONSABILITE LIMITEE",
    "SOCIETE EN COMMANDITE PAR ACTIONS",
    "SOCIETE COOPERATIVE A RESPONSABILITE LIMITEE",
    "SOCIETE COOPERATIVE",
    "SOCIETAS EUROPAEA",
    "NAAMLOZE VENNOOTSCHAP",
    "BESLOTEN VENNOOTSCHAP MET BEPERKTE AANSPRAKELIJKHEID",
    "COOPERATIEVE VENNOOTSCHAP MET BEPERKTE AANSPRAKELIJKHEID",
    "COMMANDITAIRE VENNOOTSCHAP OP AANDELEN",
    "COOPERATIEVE VENNOOTSCHAP",
    "NV/SA",
    "SA/NV",
    "NV",
    "CVBA",
    "CVOA",
    "SCRL",
    "SCRIS",
    "SRL",
    "BV",
    "BVB",
    "VZW",
    "IVZW",
    "ASBL",
    "GMBH",
    "S A S",
    "S C A",
    "S A",
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
    punctuation and whitespace. The result is a bare ASCII token string.
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

    Exact equality wins; otherwise every token of the shorter normalized
    name must appear in the longer one (``KBC GROUP NV`` aligns with
    ``KBC GROUP``). Token-subset matching is used instead of contiguous
    containment because Belgian FSMA abbreviations are not substrings of the
    legal name (``AB INBEV`` is not part of ``ANHEUSER-BUSCH INBEV`` - such
    issuers match by ISIN only). A single token under three characters never
    matches, so ``ABI`` and ``AB`` never collide with ``AB INBEV``.
    """
    left = normalize_company_name(universe_name)
    right = normalize_company_name(record_name)
    left_tokens = left.split()
    right_tokens = right.split()
    if not left_tokens or not right_tokens:
        return False
    if left == right:
        return True
    if len(left_tokens) <= len(right_tokens):
        shorter, longer = left_tokens, right_tokens
    else:
        shorter, longer = right_tokens, left_tokens
    if len(shorter) == 1 and len(shorter[0]) < 3:
        return False
    return all(token in longer for token in shorter)


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


class StoriCompanyMatcher:
    """Match parsed STORI records against a universe identity.

    An identity is the BE universe cache entry for a requested ticker
    (company name and/or Belgian ISIN). The ticker is never part of the
    pattern; a record matches when its official company name aligns with the
    universe name or its ISIN list contains the universe ISIN.
    """

    def matches(
        self,
        record: Mapping[str, Any],
        *,
        name: str,
        isin: str,
    ) -> bool:
        if isin:
            codes = tuple(record.get("isin_codes") or ())
            if str(isin).strip().upper() in codes:
                return True
            raw = record.get("raw")
            if record_has_isin(raw if isinstance(raw, Mapping) else record, isin):
                return True
        if name:
            company = str(record.get("company") or "").strip()
            if company and company_names_match(name, company):
                return True
        return False
