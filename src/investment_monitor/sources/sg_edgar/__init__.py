"""Explicitly mapped Singapore issuer fallback via US SEC EDGAR.

EDGAR records are US regulatory filings.  They supplement an SG listing only
when an operator has reviewed the SGX-to-SEC identity relation; they are never
represented as SGXNET announcements.
"""

from .connector import (
    IDENTITY_SCHEMA,
    SgEdgarCollectionFailure,
    SgEdgarConnector,
    SgEdgarDataError,
    SgEdgarIdentity,
    load_identities_from_path,
)

__all__ = [
    "IDENTITY_SCHEMA", "SgEdgarCollectionFailure", "SgEdgarConnector",
    "SgEdgarDataError", "SgEdgarIdentity", "load_identities_from_path",
]
