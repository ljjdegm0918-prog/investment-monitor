"""Xueqiu (雪球) CN/HK community connector (stub + optional cookie LIVE)."""

from __future__ import annotations

import json
import logging
import os
from datetime import date, datetime, timezone
from typing import List, Optional, Sequence, Tuple
from urllib.request import Request, urlopen

from ...connectors.base import SecretField
from ...models import (
    MARKET_CN,
    MARKET_HK,
    CollectionRequest,
    InformationItem,
)
from ...web_repository import normalize_xq_symbol
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
DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/126.0.0.0 Safari/537.36"
)
def _cookie_configured() -> bool:
    return bool(os.environ.get("XUEQIU_COOKIE", "").strip())


class XueqiuConnector:
    """CN/HK community source for Xueqiu statuses.

    Without ``XUEQIU_COOKIE``: honest ``stub`` — ``collect()`` returns ``[]``.
    With a non-empty cookie: attempt official ``statuses/search.json``, filter
    by market calendar day, and map structured posts. Failed/rejected cookie
    falls back to stub notes per ticker.
    """

    name = "xueqiu"
    provider = "Xueqiu"
    _STUB_STATUS = "stub"
    _LIVE_VIA_COOKIE_STATUS = "LIVE(cookie)"
    secret_fields = (
        SecretField(
            env="XUEQIU_COOKIE",
            label="Xueqiu session cookie",
            kind="password",
            help="Browser Cookie header value containing xq_a_token=... for statuses/search.json.",
        ),
    )

    def __init__(self) -> None:
        self._last_errors: Tuple[Tuple[str, str], ...] = ()
        self._status = self._STUB_STATUS

    @property
    def last_errors(self) -> Tuple[Tuple[str, str], ...]:
        return self._last_errors

    @property
    def status(self) -> str:
        """Instance status: stub, or LIVE(cookie) after a successful live path."""
        return self._status

    @classmethod
    def configuration_error(cls) -> Optional[str]:
        """Not used by registry for Xueqiu.

        Missing cookie is an honest stub, not an unavailable connector. Settings
        still exposes ``secret_fields`` so a cookie can unlock LIVE.
        """
        return None

    def _fetch_via_cookie(
        self,
        ticker: str,
        market: str,
        *,
        start_date: date,
        end_date: date,
    ) -> Optional[List[InformationItem]]:
        """Fetch via official JSON API.

        Returns a list (possibly empty after day filter) on HTTP/JSON success,
        or ``None`` when the cookie/token/WAF path failed.
        """
        code = normalize_xq_symbol(ticker, market=market)
        cookie = os.environ.get("XUEQIU_COOKIE", "").strip()
        if not cookie:
            return None

        url = (
            f"https://xueqiu.com/statuses/search.json"
            f"?symbol={code}&count=20"
        )
        try:
            req = Request(
                url,
                headers={
                    "User-Agent": DEFAULT_USER_AGENT,
                    "Accept": "application/json, text/plain, */*",
                    "Cookie": cookie,
                },
            )
            with urlopen(req, timeout=20) as resp:
                body = resp.read().decode("utf-8", errors="replace")
                data = json.loads(body)
        except Exception as exc:  # noqa: BLE001
            LOGGER.debug("xueqiu cookie fetch failed for %s: %s", ticker, exc)
            return None

        if not isinstance(data, dict):
            return None

        error_code = data.get("error_code")
        if error_code is None:
            error_code = data.get("err_code")
        if error_code is not None and str(error_code) not in ("0", ""):
            LOGGER.info(
                "xueqiu ticker=%s cookie/API error_code=%s — stub fallthrough",
                ticker,
                error_code,
            )
            return None

        posts = data.get("list") or data.get("response") or data.get("data") or []
        if not isinstance(posts, list):
            return None

        collected = datetime.now(timezone.utc)
        items: List[InformationItem] = []
        for post in posts:
            if not isinstance(post, dict):
                continue
            status_id = str(post.get("id") or post.get("status_id") or "").strip()
            if not status_id:
                continue
            title = str(post.get("title") or post.get("description") or "").strip()
            if not title:
                title = str(post.get("text") or f"Xueqiu status {status_id}").strip()[:500]
            published_at = self._parse_published_at(post)
            day = local_day(published_at, market)
            if day < start_date or day > end_date:
                continue
            user_id = str(post.get("user_id") or (post.get("user") or {}).get("id") or "").strip()
            deeplink = (
                f"https://xueqiu.com/{user_id}/{status_id}"
                if user_id
                else SYMBOL_URL_TEMPLATE.format(symbol=code)
            )
            summary = str(
                post.get("description") or post.get("text") or post.get("summary") or ""
            ).strip()[:500] or None
            items.append(
                InformationItem(
                    source=self.name,
                    source_type="community",
                    external_id=f"xueqiu-{status_id}",
                    tickers=(code,),
                    issuer=code,
                    published_at=published_at.astimezone(timezone.utc),
                    title=title[:500],
                    document_type="community_post",
                    url=deeplink,
                    collected_at=collected,
                    raw_metadata={
                        "provider": "xueqiu",
                        "status_id": status_id,
                        "stock_code": code,
                        "symbol_url": SYMBOL_URL_TEMPLATE.format(symbol=code),
                        "stub": False,
                        "via": "cookie",
                        "market": market,
                        "local_day": day.isoformat(),
                    },
                    market=market,
                    summary=summary,
                    effective_at=published_at.astimezone(timezone.utc),
                )
            )
        return items

    @staticmethod
    def _parse_published_at(post: dict) -> datetime:
        """Parse Xueqiu timestamps (ISO string or epoch ms/seconds)."""
        for key in ("created_at", "timestamp", "time"):
            raw = post.get(key)
            if raw is None or raw == "":
                continue
            if isinstance(raw, (int, float)):
                value = float(raw)
                if value > 1e12:
                    value /= 1000.0
                return datetime.fromtimestamp(value, tz=timezone.utc)
            text = str(raw).strip()
            if text.isdigit():
                value = float(text)
                if value > 1e12:
                    value /= 1000.0
                return datetime.fromtimestamp(value, tz=timezone.utc)
            try:
                return datetime.fromisoformat(text.replace("Z", "+00:00"))
            except ValueError:
                continue
        return datetime.now(timezone.utc)

    def collect(self, request: CollectionRequest) -> List[InformationItem]:
        """Collect Xueqiu posts for all CN/HK tickers in the request."""
        notes: List[Tuple[str, str]] = []
        collected: List[InformationItem] = []
        live_mode = _cookie_configured()
        any_live_success = False

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
                fetched = self._fetch_via_cookie(
                    ticker,
                    market,
                    start_date=request.start_date,
                    end_date=request.end_date,
                )
                if fetched is not None:
                    any_live_success = True
                    collected.extend(fetched)
                    notes.append(
                        (
                            code,
                            f"xueqiu LIVE via XUEQIU_COOKIE items={len(fetched)}",
                        )
                    )
                    LOGGER.info(
                        "xueqiu ticker=%s market=%s status=live cookie items=%s",
                        ticker,
                        market,
                        len(fetched),
                    )
                    continue

            notes.append(
                (
                    code,
                    (
                        f"xueqiu stub: public symbol page "
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

        self._status = (
            self._LIVE_VIA_COOKIE_STATUS if any_live_success else self._STUB_STATUS
        )
        self._last_errors = tuple(notes)
        return collected

    def map_rows_for_tests(
        self,
        rows: Sequence[XueqiuPostRow],
        *,
        ticker: str,
        market: str,
        collected_at: Optional[datetime] = None,
    ) -> List[InformationItem]:
        """Map parsed rows to InformationItems (unit tests / fixtures)."""
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
                        "symbol_url": SYMBOL_URL_TEMPLATE.format(symbol=code),
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
