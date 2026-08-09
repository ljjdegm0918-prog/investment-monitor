"""Google News 德国市场 RSS 客户端（DE-3 留桩）。

URL 模板占位：
``https://news.google.com/rss/search?q={query}&hl=de&gl=DE&ceid=DE:de``。

留桩阶段不发起真实请求：``fetch_news`` 显式抛 ``NotImplementedError``，
避免把未实现的采集伪装成成功。请求代码沿用 Yahoo DE 的 ``.DE`` 后缀。
"""

from __future__ import annotations

from datetime import date
from typing import Any, List, Mapping
from urllib.parse import quote

DEFAULT_BASE_URL = "https://news.google.com/rss/search"


class GoogleDeNewsError(Exception):
    """Google News DE 新闻采集基础错误（留桩）。"""


class GoogleDeNewsRequestError(GoogleDeNewsError):
    """请求无法完成时抛出（留桩）。"""


class GoogleDeNewsDataError(GoogleDeNewsError):
    """返回意外内容时抛出（留桩）。"""


class GoogleDeNewsClient:
    """Google News 德国市场新闻客户端（留桩，未实现）。"""

    def __init__(self, base_url: str = DEFAULT_BASE_URL) -> None:
        if not base_url.strip():
            raise ValueError("Google DE news base URL must not be empty.")
        self._base_url = base_url.rstrip("/")

    @property
    def base_url(self) -> str:
        """URL 模板占位：Google News DE 请求地址。"""
        return self._base_url

    def url_for(self, query: str) -> str:
        """按占位模板构造请求 URL：德语、DE 区域。"""
        return f"{self._base_url}?q={quote(query)}&hl=de&gl=DE&ceid=DE:de"

    def fetch_news(
        self,
        query: str,
        start_date: date,
        end_date: date,
    ) -> List[Mapping[str, Any]]:
        """DE-3 留桩：未实现，明确抛错而非伪造空结果。"""
        raise NotImplementedError(
            "Google DE news is a stub in DE-3; fetch_news is not implemented."
        )
