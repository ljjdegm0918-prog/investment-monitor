"""Yahoo Finance DE 新闻连接器（DE-3 留桩，仅 market=de 收集）。"""

from __future__ import annotations

import logging
from typing import Callable, List, Optional, Tuple

from ....models import CollectionRequest, InformationItem, MARKET_DE
from ....web_repository import normalize_de_ticker
from ..symbols import de_yahoo_symbol
from .client import YahooDeNewsClient

LOGGER = logging.getLogger(__name__)

MAX_LOOKBACK_DAYS = 30


class YahooDeNewsConnector:
    """Yahoo Finance 德国市场新闻连接器（留桩）。

    只接受 market=de；其余市场零 HTTP 直接跳过。DE-3 阶段对 market=de
    显式抛 ``NotImplementedError``（诚实留桩，不伪造结果）。
    """

    name = "yahoo_de"
    provider = "Yahoo Finance DE"
    max_lookback_days = MAX_LOOKBACK_DAYS

    def __init__(
        self,
        client: Optional[YahooDeNewsClient] = None,
        symbol_for: Optional[Callable[[str], str]] = None,
    ) -> None:
        self._client = client or YahooDeNewsClient()
        self._symbol_for = symbol_for or de_yahoo_symbol
        self._last_errors: Tuple[Tuple[str, str], ...] = ()

    @property
    def last_errors(self) -> Tuple[Tuple[str, str], ...]:
        return self._last_errors

    def collect(self, request: CollectionRequest) -> List[InformationItem]:
        for ticker in request.tickers:
            if request.market_for(ticker) != MARKET_DE:
                LOGGER.info(
                    "yahoo_de ticker=%s market=%s skipped not_de_market",
                    ticker,
                    request.market_for(ticker),
                )
                continue
            code = normalize_de_ticker(ticker)
            self._symbol_for(code)
            raise NotImplementedError(
                "Yahoo DE news is a stub in DE-3; collect is not implemented."
            )
        return []
