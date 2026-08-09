"""Yahoo Finance 德国市场新闻 RSS 客户端（DE-3 留桩）。

URL 模板占位：
``https://feeds.finance.yahoo.com/rss/2.0/headline?s={symbol}&region=DE&lang=de-DE``。

留桩阶段不发起真实请求：``fetch_news`` 显式抛 ``NotImplementedError``，
避免把未实现的采集伪装成成功。仅接受 ``.DE`` 后缀的请求代码。
"""

from __future__ import annotations

from datetime import date
from typing import Any, List, Mapping

DEFAULT_BASE_URL = "https://feeds.finance.yahoo.com/rss/2.0/headline"


class YahooDeNewsError(Exception):
    """Yahoo Finance DE 新闻采集基础错误（留桩）。"""


class YahooDeNewsRequestError(YahooDeNewsError):
    """请求无法完成时抛出（留桩）。"""


class YahooDeNewsDataError(YahooDeNewsError):
    """返回意外内容时抛出（留桩）。"""


class YahooDeNewsClient:
    """Yahoo Finance 德国市场新闻客户端（留桩，未实现）。"""

    def __init__(self, base_url: str = DEFAULT_BASE_URL) -> None:
        if not base_url.strip():
            raise ValueError("Yahoo DE news base URL must not be empty.")
        self._base_url = base_url.rstrip("/")

    @property
    def base_url(self) -> str:
        """URL 模板占位：Yahoo DE 请求地址。"""
        return self._base_url

    def url_for(self, symbol: str) -> str:
        """按占位模板构造请求 URL：DE 区域、德语。"""
        return f"{self._base_url}?s={symbol}&region=DE&lang=de-DE"

    def fetch_news(
        self,
        symbol: str,
        start_date: date,
        end_date: date,
    ) -> List[Mapping[str, Any]]:
        """DE-3 留桩：未实现，明确抛错而非伪造空结果。"""
        raise NotImplementedError(
            "Yahoo DE news is a stub in DE-3; fetch_news is not implemented."
        )
