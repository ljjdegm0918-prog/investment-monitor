"""Parse Stockhead.com.au WordPress search RSS (AU ASX news/analysis).

Spike 2026-08-12: ``https://stockhead.com.au/?s={TICKER}&feed=rss2``
returns a live WordPress RSS 2.0 feed. Each item carries category tags in
``CompanyName - TICKER`` format that allow reliable per-ticker filtering.
GUIDs are empty; URL path slugs serve as stable external IDs.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime, timezone
from email.utils import parsedate_to_datetime
from typing import List, Optional
from xml.etree import ElementTree as ET
from zoneinfo import ZoneInfo

SYDNEY = ZoneInfo("Australia/Sydney")
MAX_SUMMARY_LEN = 500

# category CDATA 格式: "CompanyName - TICKER"（如 "BHP - BHP" 或 "Santos - STO"）
_CAT_TICKER = re.compile(r"^.+\s+-\s+(?P<code>[A-Z0-9]{2,6})$")

# 从 URL 路径中提取 slug 作为稳定外部 ID
# 例: .../news/bhp-flags-copper-expansion/ → bhp-flags-copper-expansion
_SLUG_FROM_URL = re.compile(
    r"https?://(?:www\.)?stockhead\.com\.au/[^/]+/(?P<slug>[^/?#]+)/?$"
)

# WordPress RSS 命名空间
_NS_CONTENT = "http://purl.org/rss/1.0/modules/content/"
_NS_DC = "http://purl.org/dc/elements/1.1/"


@dataclass(frozen=True)
class StockheadFeedRow:
    """一条 Stockhead RSS 条目。"""

    article_slug: str  # URL path slug，用作外部 ID
    title: str
    url: str
    published_at: datetime
    summary: Optional[str] = None


def sydney_day(moment: datetime) -> date:
    """把 UTC 时刻转换为悉尼本地日历日。"""
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment.astimezone(SYDNEY).date()


def parse_stockhead_search_rss(
    xml_text: str,
    *,
    ticker: str,
    on_date: date,
) -> List[StockheadFeedRow]:
    """解析 Stockhead 搜索 RSS，返回匹配 ticker 且悉尼日期等于 on_date 的条目。

    过滤策略：
    1. 至少一个 ``<category>`` 标签中 ticker 与 ``CompanyName - {TICKER}`` 中的
       code 字段完全匹配（大写）。
    2. ``pubDate`` 转换为悉尼时区后的日历日等于 ``on_date``。

    使用 XML ElementTree 解析以正确处理 CDATA 和命名空间。
    """
    code = ticker.strip().upper()
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return []

    rows: List[StockheadFeedRow] = []
    for item in root.findall("./channel/item"):
        # 检查 ticker 分类标签
        categories = [
            (elem.text or "").strip()
            for elem in item.findall("category")
        ]
        if not _item_has_ticker(categories, code):
            continue

        # 解析发布时间
        pub_raw = (item.findtext("pubDate") or "").strip()
        if not pub_raw:
            continue
        published = _parse_pub_date(pub_raw)
        if published is None:
            continue

        # 悉尼日期过滤
        if sydney_day(published) != on_date:
            continue

        # 提取 URL 和 slug
        link = (item.findtext("link") or "").strip()
        if not link:
            continue
        slug = _slug_from_url(link)
        if not slug:
            continue

        # 标题
        title = (item.findtext("title") or "").strip()
        if not title:
            title = slug.replace("-", " ").title()

        # 摘要（RSS <description> 含 HTML，取纯文本前缀）
        desc_raw = (item.findtext("description") or "").strip()
        summary = _strip_html(desc_raw)[:MAX_SUMMARY_LEN] or None

        rows.append(
            StockheadFeedRow(
                article_slug=slug,
                title=title[:500],
                url=link,
                published_at=published,
                summary=summary,
            )
        )

    # 去重（同一 slug 第一条优先）
    seen: set[str] = set()
    unique: List[StockheadFeedRow] = []
    for row in rows:
        if row.article_slug in seen:
            continue
        seen.add(row.article_slug)
        unique.append(row)
    return unique


# ---------------------------------------------------------------------------
# 内部辅助函数
# ---------------------------------------------------------------------------

def _item_has_ticker(categories: List[str], code: str) -> bool:
    """检查 category 列表中是否有 'CompanyName - CODE' 格式匹配。"""
    for cat in categories:
        m = _CAT_TICKER.match(cat)
        if m and m.group("code").upper() == code:
            return True
    return False


def _slug_from_url(url: str) -> str:
    """从 Stockhead 文章 URL 提取路径 slug。"""
    m = _SLUG_FROM_URL.match(url)
    if m:
        return m.group("slug")
    # 回退：取最后一段路径
    path = url.rstrip("/").rsplit("/", 1)[-1]
    return path if path else ""


def _parse_pub_date(raw: str) -> Optional[datetime]:
    """解析 RFC 2822 格式日期（WordPress pubDate）。"""
    try:
        parsed = parsedate_to_datetime(raw)
    except (TypeError, ValueError, IndexError):
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


_HTML_TAG = re.compile(r"<[^>]+>")


def _strip_html(html: str) -> str:
    """去除 HTML 标签，返回纯文本。"""
    return _HTML_TAG.sub("", html).strip()
