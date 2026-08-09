"""DE 新闻源请求时使用的代码规则（DE-3 留桩）。"""

from __future__ import annotations

from ...web_repository import normalize_de_ticker


def de_yahoo_symbol(ticker: str) -> str:
    """规范 DE 代码加 ``.DE`` 后缀用于请求；存储代码不带后缀。

    输入先做 ``normalize_de_ticker`` 归一（剥离 .DE/.XE/.XETRA/.F 等），
    再追加 ``.DE``，避免把 ``SAP.XETRA`` 拼成 ``SAP.XETRA.DE``。
    """
    code = normalize_de_ticker(ticker)
    return f"{code}.DE"
