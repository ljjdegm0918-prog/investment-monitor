"""AFM official inside-information register connector for the Netherlands."""

from .client import (
    AFM_CONTEXT_ID,
    AFM_PAGE_SIZE,
    AfmNlClient,
    AfmNlDataError,
    AfmNlRequestError,
    parse_afm_page,
)
from .connector import AfmNlConnector

__all__ = [
    "AFM_CONTEXT_ID",
    "AFM_PAGE_SIZE",
    "AfmNlClient",
    "AfmNlConnector",
    "AfmNlDataError",
    "AfmNlRequestError",
    "parse_afm_page",
]
