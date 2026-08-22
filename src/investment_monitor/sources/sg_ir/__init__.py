"""Configured Singapore issuer investor-relations disclosure feeds."""

from .connector import (
    builtin_sg_ir_sources,
    SG_IR_CONFIG_SCHEMA,
    SgIrConnector,
    SgIrDataError,
    SgIrRequestError,
    SgIrSource,
    SgIrUrlRule,
    load_sources_from_path,
)

__all__ = [
    "builtin_sg_ir_sources",
    "SG_IR_CONFIG_SCHEMA", "SgIrConnector", "SgIrDataError",
    "SgIrRequestError", "SgIrSource", "SgIrUrlRule", "load_sources_from_path",
]
