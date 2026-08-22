"""Issuer-configured Canadian investor-relations filing feeds.

This is a Tier 2, opt-in source.  It is deliberately not an official SEDAR+
replacement and it never discovers or ingests general newswire feeds.
"""

from .connector import (
    CONFIG_SCHEMA,
    CaIrConnector,
    CaIrDataError,
    CaIrError,
    CaIrRequestError,
    CaIrResponse,
    CaIrSource,
    CaIrUrlRule,
    classify_ca_filing,
    load_sources_from_path,
)

__all__ = [
    "CONFIG_SCHEMA",
    "CaIrConnector",
    "CaIrDataError",
    "CaIrError",
    "CaIrRequestError",
    "CaIrResponse",
    "CaIrSource",
    "CaIrUrlRule",
    "classify_ca_filing",
    "load_sources_from_path",
]
