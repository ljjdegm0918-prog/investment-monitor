"""Stockhead AU connector — live WordPress search RSS (ASX news/analysis).

Spike 2026-08-12: Stockhead.com.au 是 ASX 小/中市值个股的澳洲新闻分析站。
公开 WordPress 搜索 RSS ``/?s={TICKER}&feed=rss2`` 可免登录访问，返回
含 ticker 分类标签（``CompanyName - TICKER``）的 RSS 2.0 feed。

注：connector 名 ``stockhead_au``，独立于 ``hotcopper_au``（保持 stub）。
HotCopper 主域仍全域 403；Stockhead 是不同来源，不可混淆。
"""

from __future__ import annotations

import logging
from datetime import date, datetime, timezone
from typing import Callable, List, Optional, Sequence, Tuple
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from ...models import MARKET_AU, CollectionRequest, InformationItem
from ...web_repository import normalize_au_ticker
from .parser import StockheadFeedRow, sydney_day, parse_stockhead_search_rss

LOGGER = logging.getLogger(__name__)

# 搜索 RSS URL 模板（WordPress 内置）
SEARCH_RSS_TEMPLATE = "https://stockhead.com.au/?s={ticker}&feed=rss2"
DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (compatible; InvestmentMonitor/0.1; +https://example.local)"
)


class StockheadRequestError(RuntimeError):
    """单 ticker Stockhead RSS 抓取失败时抛出。"""


class StockheadAuConnector:
    """AU 新闻/分析源，使用 Stockhead.com.au WordPress 搜索 RSS。

    ``status="live"``：``collect()`` 通过公开搜索 RSS 按 ticker+悉尼日期抓取
    结构化条目（标题/时间/摘要/deeplink）。无需登录，无 Cloudflare WAF。

    注：Stockhead 是新闻分析站，非 HotCopper 社区论坛替代；这是独立来源，
    connector 名称不同，source_type 仍用 ``community`` 以与项目社区分类对齐。
    """

    name = "stockhead_au"
    provider = "Stockhead"
    status = "live"

    def __init__(
        self,
        *,
        user_agent: str = DEFAULT_USER_AGENT,
        fetch_xml: Optional[Callable[[str], str]] = None,
    ) -> None:
        self._user_agent = user_agent
        # 允许注入 fetch_xml 以便单测 mock
        self._fetch_xml = fetch_xml or self._fetch_search_rss
        self._last_errors: Tuple[Tuple[str, str], ...] = ()

    @property
    def last_errors(self) -> Tuple[Tuple[str, str], ...]:
        return self._last_errors

    def collect(self, request: CollectionRequest) -> List[InformationItem]:
        """按 ticker + 日期范围采集 Stockhead 文章。"""
        items: List[InformationItem] = []
        failures: List[Tuple[str, str]] = []
        collected_at = datetime.now(timezone.utc)

        for ticker in request.tickers:
            code = normalize_au_ticker(ticker)
            market = request.market_for(code)
            if market != MARKET_AU:
                LOGGER.info(
                    "stockhead_au ticker=%s market=%s skipped not_au_market",
                    ticker,
                    market,
                )
                continue
            try:
                xml_text = self._fetch_xml(code)
                # RSS 是滚动 ~50 条窗口；对请求日期范围内每天独立过滤
                day = request.start_date
                while day <= request.end_date:
                    rows = parse_stockhead_search_rss(
                        xml_text, ticker=code, on_date=day
                    )
                    items.extend(
                        self.map_rows(
                            rows,
                            ticker=code,
                            collected_at=collected_at,
                        )
                    )
                    day = date.fromordinal(day.toordinal() + 1)
            except Exception as error:
                message = str(error) or error.__class__.__name__
                failures.append((code, message))
                LOGGER.warning(
                    "stockhead_au ticker=%s status=failure error=%s",
                    code,
                    message,
                )

        self._last_errors = tuple(failures)
        if len(request.tickers) == 1 and failures:
            raise StockheadRequestError(failures[0][1])
        return items

    def map_rows(
        self,
        rows: Sequence[StockheadFeedRow],
        *,
        ticker: str,
        collected_at: Optional[datetime] = None,
    ) -> List[InformationItem]:
        """将解析行映射为 InformationItem 列表（也可供单测直接调用）。"""
        code = normalize_au_ticker(ticker)
        collected = collected_at or datetime.now(timezone.utc)
        items: List[InformationItem] = []
        for row in rows:
            items.append(
                InformationItem(
                    source=self.name,
                    source_type="community",
                    external_id=f"stockhead-{row.article_slug}",
                    tickers=(code,),
                    issuer=code,
                    published_at=row.published_at.astimezone(timezone.utc),
                    title=row.title,
                    document_type="community_post",
                    url=row.url,
                    collected_at=collected,
                    raw_metadata={
                        "provider": "stockhead",
                        "article_slug": row.article_slug,
                        "stock_code": code,
                        "feed_url": SEARCH_RSS_TEMPLATE.format(ticker=code),
                        "sydney_day": sydney_day(row.published_at).isoformat(),
                    },
                    market=MARKET_AU,
                    summary=row.summary,
                    effective_at=row.published_at.astimezone(timezone.utc),
                )
            )
        return items

    def _fetch_search_rss(self, ticker: str) -> str:
        """从 Stockhead 搜索 RSS 抓取 XML 文本。"""
        url = SEARCH_RSS_TEMPLATE.format(ticker=ticker)
        request = Request(
            url,
            headers={
                "User-Agent": self._user_agent,
                "Accept": "application/rss+xml, application/xml, text/xml, */*",
            },
        )
        try:
            with urlopen(request, timeout=30) as response:
                return response.read().decode("utf-8", "replace")
        except HTTPError as error:
            raise StockheadRequestError(
                f"stockhead_au feed HTTP {error.code} for ticker {ticker!r}"
            ) from error
        except URLError as error:
            raise StockheadRequestError(
                f"stockhead_au feed network error for {ticker!r}: {error.reason}"
            ) from error
