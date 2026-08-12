"""Xueqiu (雪球) CN/HK community connector — honest stub after spike.

Live public HTML/JSON collection is **not** wired: every xueqiu.com HTML
request is answered by an Aliyun WAF JS-challenge shell, and the JSON APIs
(``search.json``, ``query/v1/symbol/search/status.json``,
``statuses/hot/listV2.json``) demand a valid ``xq_a_token`` session cookie
(error ``400016``) (spike 2026-08-11). Do not enable login/WAF bypass
scraping. ``collect()`` returns an empty list until a stable public
day-filter feed exists.
"""

from .connector import XueqiuConnector, local_day, parse_board_html_for_day
from .parser import parse_xueqiu_status_list

__all__ = [
    "XueqiuConnector",
    "local_day",
    "parse_board_html_for_day",
    "parse_xueqiu_status_list",
]
