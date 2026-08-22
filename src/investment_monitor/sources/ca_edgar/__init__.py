"""Explicitly mapped Canadian issuer fallback via US SEC EDGAR.

This is intentionally separate from the US ``sec`` connector: an EDGAR
accession collected for a Canadian listing must not overwrite the US-market
record with the same SEC source/id pair.
"""

from .connector import (
    IDENTITY_SCHEMA,
    CaEdgarCollectionFailure,
    CaEdgarConnector,
    CaEdgarDataError,
    CaEdgarIdentity,
    load_identities_from_path,
)

__all__ = [
    "IDENTITY_SCHEMA",
    "CaEdgarCollectionFailure",
    "CaEdgarConnector",
    "CaEdgarDataError",
    "CaEdgarIdentity",
    "load_identities_from_path",
]
