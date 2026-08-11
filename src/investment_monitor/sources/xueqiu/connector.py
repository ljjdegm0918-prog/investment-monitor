"""Xueqiu (雪球) CN/HK community connector (supports stub + optional cookie LIVE)."""

from __future__ import annotations

import json
import logging
import os
from datetime import date, datetime, timezone
from typing import List, Optional, Sequence, Tuple
from zoneinfo import ZoneInfo

from ...models import (
    MARKET_CN,
    MARKET_HK,
    CollectionRequest,
    InformationItem,
)
from ...web_repository import normalize_cn_ticker, normalize_xq_symbol
from .parser import (
    HONG_KONG,
    SHANGHAI,
    XueqiuPostRow,
    parse_xueqiu_status_list,
)

LOGGER = logging.getLogger(__name__)

# Documented public symbol page URL pattern (Aliyun WAF JS-challenge to
# automated clients; JSON APIs require xq_a_token, 2026-08-11).
SYMBOL_URL_TEMPLATE = "https://xueqiu.com/S/{symbol}"

# Optional cookie-backed LIVE path. Read dynamically via os.getenv()
# so that @patch.dict / .env changes are picked up each time collect() runs.


class XueqiuConnector:
    """CN/HK community source for Xueqiu public statuses.

    ``status="stub"``: ``collect()`` does not hit the network and returns
    ``[]``. Parser helpers remain unit-tested against fixtures for a future
    unlock.
    """

    name = "xueqiu"
    provider = "Xueqiu"
    _STUB_STATUS = "stub"
    _LIVE_VIA_COOKIE_STATUS = "LIVE(cookie)"

    def __init__(self) -> None:
        self._last_errors: Tuple[Tuple[str, str], ...] = ()
        self._status = self._STUB_STATUS  # default; overridden by collect() if cookie path taken

    @property
    def last_errors(self) -> Tuple[Tuple[str, str], ...]:
        return self._last_errors

    @property
    def status(self) -> str:
        """Return the current connector status.

        - ``"stub"`` when no ``XUEQIU_COOKIE`` is configured, or when the
          cookie-backed LIVE attempt failed/fell back.
        - ``"live(cookie)"`` when ``XUEQIU_COOKIE`` is set and the JSON API
          path was successfully entered (even if it returned zero posts).
        """
        return self._status

    def _fetch_via_cookie(self, ticker: str, market: str) -> Optional[List[InformationItem]]:
        """Try to fetch Xueqiu posts via the official JSON API using a cookie.

        Returns a list of InformationItem if the API call succeeds, or None
        when the response indicates token error / WAF page etc.
        """
        code = normalize_xq_symbol(ticker, market=market)
        cookie = os.getenv("XUEQIU_COOKIE")
        if not cookie:
            return None

        url = (
            f"https://xueqiu.com/statuses/search.json"
            f"?symbol={code}&count=10"
        )
        try:
            import urllib.request

            req = urllib.request.Request(
                url,
                headers={
                    "User-Agent": (
                        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) "
                        "Chrome/126.0.0.0 Safari/537.36"
                    ),
                    "Accept": "application/json, text/plain, */*",
                    "Cookie": cookie,
                },
            )
            with urllib.request.urlopen(req, timeout=20) as resp:
                body = resp.read().decode("utf-8", errors="replace")
                # Some endpoints return JSON wrapped in a callback or gzip.
                data = json.loads(body)
        except Exception as exc:  # noqa: BLE001
            LOGGER.debug("xueqiu cookie fetch failed for %s: %s", ticker, exc)
            return None

        # Validate we got real data and not a WAF/error response.
        if not isinstance(data, dict):
            return None

        error_code = data.get("error_code") or data.get("err_code")
        if error_code and str(error_code) == "400016":
            # Token invalid/rejected — fall back to stub.
            LOGGER.info(
                "xueqiu ticker=%s cookie rejected (400016) — stub fallthrough",
                ticker,
            )
            return None

        # Extract status list from the response.
        # The search.json response structure: {"error_code":0,"response":[...]}
        posts = data.get("response") or data.get("data") or []
        if not isinstance(posts, list):
            return None

        zone = SHANGHAI if market == MARKET_CN else HONG_KONG
        rows: List[XueqiuPostRow] = []
        for post in posts:
            status_id = str(post.get("status_id") or post.get("id") or "")
            title = str(post.get("title") or "").strip()
            if not title:
                title = f"Xueqiu status {status_id}"[:500]
            # published_at is an ISO timestamp string.
            ts = str(post.get("timestamp") or post.get("created_at") or "")
            published_at: Optional[datetime] = None
            if ts:
                try:
                    published_at = datetime.fromisoformat(
                        ts.replace("Z", "+00:00")
                    )
                except ValueError:
                    pass
            url = f"https://xueqiu.com/{post.get('user_id') or ''}/{status_id}"
            summary = str(post.get("summary") or post.get("description") or "")[:500] or None
            # Determine a local date for day-filtering; if none, use now.
            if published_at:
                published_local = published_at.astimezone(zone).date()
            else:
                published_local = date.today()

            rows.append(
                XueqiuPostRow(
                    status_id=status_id,
                    title=title,
                    url=url,
                    published_at=published_at or datetime.now(timezone.utc),
                    summary=summary,
                )
            )

        # Map parsed rows to InformationItems via the existing test helper logic.
        items: List[InformationItem] = []
        for row in rows:
            from .parser import _market_zone  # local import to avoid cycle

            code2 = normalize_xq_symbol(ticker, market=market)
            collected = datetime.now(timezone.utc)
            itm: InformationItem = InformationItem(
                source=self.name,
                source_type="community",
                external_id=f"xueqiu-{row.status_id}",
                tickers=(code2,),
                issuer=code2,
                published_at=row.published_at,
                title=row.title,
                document_type="community_post",
                url=row.url,
                collected_at=collected,
                raw_metadata={
                    "provider": "xueqiu",
                    "status_id": row.status_id,
                    "stock_code": code2,
                    "symbol_url": SYMBOL_URL_TEMPLATE.format(
                        symbol=code2
                    ),
                    "stub": False,
                    "via": "cookie",
                    "market": market,
                },
                market=market,
                summary=(row.summary or None)[:500],
                effective_at=row.published_at,
            )
            items.append(itm)

        return items

    def collect(self, request: CollectionRequest) -> List[InformationItem]:
        """Collect Xueqiu posts.

        If ``XUEQIU_COOKIE`` env var is set, attempt the official JSON API
        path and return real structured items.  When no cookie is configured
        the connector honestly degrades to stub (``collect()`` returns ``[]``).
        """
        notes: List[Tuple[str, str]] = []
        live_mode = os.getenv("XUEQIU_COOKIE") is not None
        for ticker in request.tickers:
            market = request.market_for(ticker)
            if market not in (MARKET_CN, MARKET_HK):
                LOGGER.info(
                    "xueqiu ticker=%s market=%s skipped not_cn_hk",
                    ticker,
                    market,
                )
                continue
            code = normalize_xq_symbol(ticker, market=market)

            if live_mode:
                items = self._fetch_via_cookie(ticker, market)
                if items is not None:
                    # Live path succeeded — record notes and return items.
                    self._status = self._LIVE_VIA_COOKIE_STATUS
                    for itm in items:
                        notes.append(
                            (itm.tickers[0], "xueqiu LIVE via XUEQIU_COOKIE")
                        )
                    LOGGER.info(
                        "xueqiu ticker=%s market=%s status=live cookie-enabled",
                        ticker,
                        market,
                    )
                    self._last_errors = tuple(notes)
                    return items
                # _fetch_via_cookie returned None → fall through to stub below.

            # Honest stub path (either no cookie, or cookie was rejected).
            notes.append(
                (
                    code,
                    (
                        "xueqiu stub: public symbol page "
                        f"{SYMBOL_URL_TEMPLATE.format(symbol=code)} is an "
                        "Aliyun WAF JS-challenge shell and the JSON APIs "
                        "require a valid xq_a_token session cookie (error "
                        "400016) (spike 2026-08-11); login/WAF bypass "
                        "content is out of scope"
                    ),
                )
            )
            LOGGER.info(
                "xueqiu ticker=%s symbol=%s status=stub empty",
                ticker,
                code,
            )
        self._last_errors = tuple(notes)
        return []

    def map_rows_for_tests(
        self,
        rows: Sequence[XueqiuPostRow],
        *,
        ticker: str,
        market: str,
        collected_at: Optional[datetime] = None,
    ) -> List[InformationItem]:
        """Map parsed rows to InformationItems (unit tests / future live path)."""
        code = normalize_xq_symbol(ticker, market=market)
        collected = collected_at or datetime.now(timezone.utc)
        items: List[InformationItem] = []
        for row in rows:
            summary = (row.summary or "")[:500] or None
            items.append(
                InformationItem(
                    source=self.name,
                    source_type="community",
                    external_id=f"xueqiu-{row.status_id}",
                    tickers=(code,),
                    issuer=code,
                    published_at=row.published_at.astimezone(timezone.utc),
                    title=row.title,
                    document_type="community_post",
                    url=row.url,
                    collected_at=collected,
                    raw_metadata={
                        "provider": "xueqiu",
                        "status_id": row.status_id,
                        "stock_code": code,
                        "symbol_url": SYMBOL_URL_TEMPLATE.format(
                            symbol=code
                        ),
                        "stub": True,
                    },
                    market=market,
                    summary=summary,
                    effective_at=row.published_at.astimezone(timezone.utc),
                )
            )
        return items


def local_day(moment: datetime, market: str) -> date:
    """Calendar day in the market's local zone for day filtering."""
    zone = SHANGHAI if market == MARKET_CN else HONG_KONG
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment.astimezone(zone).date()


def parse_board_html_for_day(
    html: str,
    *,
    on_date: date,
    market: str,
) -> List[XueqiuPostRow]:
    """Public helper used by unit tests (same as parser entrypoint)."""
    return parse_xueqiu_status_list(html, on_date=on_date, market=market)
