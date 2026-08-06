"""Company name/exchange resolution for HK tickers via HKEXnews."""

from __future__ import annotations

from typing import Any, Mapping, Optional

from .client import HkexNewsClient, normalize_hk_ticker


class HKEXNewsCompanyResolver:
    """Resolve HK tickers against the HKEXnews active stock list.

    The resolver never consults the SEC; unknown codes resolve to None and
    the company is added honestly as unmapped.
    """

    def __init__(self, client: Optional[HkexNewsClient] = None) -> None:
        self._client = client or HkexNewsClient.from_environment()

    def resolve(self, ticker: str) -> Optional[Mapping[str, Any]]:
        code = normalize_hk_ticker(ticker)
        stock = self._client.stock_for(code)
        if stock is None:
            return None
        return {
            "ticker": code,
            "name": str(stock.get("stock_name") or code),
            "exchange": "SEHK",
            "cik": str(stock["stock_id"]),
            "mapping_status": "mapped",
        }
