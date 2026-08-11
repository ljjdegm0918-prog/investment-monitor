"""Xueqiu (雪球) CN/HK community connector — stub + optional cookie LIVE.

Without ``XUEQIU_COOKIE``: ``collect()`` returns ``[]`` (honest stub). Public
HTML is an Aliyun WAF JS-challenge shell; JSON APIs need ``xq_a_token``
(spike 2026-08-11). With a non-empty cookie, ``statuses/search.json`` is used
and results are filtered to the request calendar day. Do not enable WAF bypass.
"""

from .connector import XueqiuConnector, local_day, parse_board_html_for_day
from .parser import parse_xueqiu_status_list

__all__ = [
    "XueqiuConnector",
    "local_day",
    "parse_board_html_for_day",
    "parse_xueqiu_status_list",
]
