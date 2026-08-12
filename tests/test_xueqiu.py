"""Unit tests for Xueqiu CN/HK stub + fixture parser (no live network)."""

from __future__ import annotations

import json
import os
import unittest
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo
from unittest.mock import patch

from investment_monitor.dedupe import annotate_feed_items, dedupe_key
from investment_monitor.models import MARKET_CN, MARKET_HK, CollectionRequest
from investment_monitor.registry import create_default_registry
from investment_monitor.sources.xueqiu import (
    XueqiuConnector,
    parse_xueqiu_status_list,
)
from investment_monitor.web_repository import (
    normalize_cn_ticker,
    normalize_hk_ticker,
    normalize_xq_symbol,
)

CN_FIXTURE = (
    Path(__file__).resolve().parent
    / "fixtures"
    / "xueqiu"
    / "sh600519_board_2026-02-17.html"
)
HK_FIXTURE = (
    Path(__file__).resolve().parent
    / "fixtures"
    / "xueqiu"
    / "hk00700_board_2026-02-17.html"
)
SHANGHAI = ZoneInfo("Asia/Shanghai")
HONG_KONG = ZoneInfo("Asia/Hong_Kong")


class XueqiuSymbolNormalizeTests(unittest.TestCase):
    def test_normalize_cn_shanghai_forms(self) -> None:
        self.assertEqual(normalize_cn_ticker("600519"), "SH600519")
        self.assertEqual(normalize_cn_ticker("600519.SS"), "SH600519")
        self.assertEqual(normalize_cn_ticker("600519.SH"), "SH600519")
        self.assertEqual(normalize_cn_ticker("SH600519"), "SH600519")
        self.assertEqual(normalize_cn_ticker("sh600519"), "SH600519")

    def test_normalize_cn_shenzhen_forms(self) -> None:
        self.assertEqual(normalize_cn_ticker("000001"), "SZ000001")
        self.assertEqual(normalize_cn_ticker("000001.SZ"), "SZ000001")
        self.assertEqual(normalize_cn_ticker("SZ000001"), "SZ000001")
        self.assertEqual(normalize_cn_ticker("300750.SZ"), "SZ300750")

    def test_normalize_cn_preserves_unknown(self) -> None:
        self.assertEqual(normalize_cn_ticker("VOD"), "VOD")

    def test_normalize_hk_root_ticker(self) -> None:
        self.assertEqual(normalize_hk_ticker("0700"), "00700")
        self.assertEqual(normalize_hk_ticker("0700.HK"), "00700")
        self.assertEqual(normalize_hk_ticker("700"), "00700")

    def test_normalize_xq_symbol_by_market(self) -> None:
        self.assertEqual(
            normalize_xq_symbol("600519", market="cn"), "SH600519"
        )
        self.assertEqual(
            normalize_xq_symbol("0700", market="hk"), "HK00700"
        )
        self.assertEqual(
            normalize_xq_symbol("0700.HK", market="hk"), "HK00700"
        )
        self.assertEqual(
            normalize_xq_symbol("VOD", market="us"), "VOD"
        )


class XueqiuParserTests(unittest.TestCase):
    def test_parser_filters_shanghai_day(self) -> None:
        html = CN_FIXTURE.read_text(encoding="utf-8")
        rows = parse_xueqiu_status_list(
            html, on_date=date(2026, 2, 17), market="cn"
        )
        self.assertEqual(len(rows), 2)
        ids = {row.status_id for row in rows}
        self.assertEqual(ids, {"2345678901", "2345678902"})
        for row in rows:
            self.assertTrue(row.title)
            self.assertTrue(row.url.startswith("https://xueqiu.com/"))
            self.assertEqual(
                row.published_at.astimezone(SHANGHAI).date(),
                date(2026, 2, 17),
            )

    def test_parser_filters_hong_kong_day(self) -> None:
        html = HK_FIXTURE.read_text(encoding="utf-8")
        rows = parse_xueqiu_status_list(
            html, on_date=date(2026, 2, 17), market="hk"
        )
        self.assertEqual(len(rows), 2)
        ids = {row.status_id for row in rows}
        self.assertEqual(ids, {"3456789011", "3456789012"})
        for row in rows:
            self.assertEqual(
                row.published_at.astimezone(HONG_KONG).date(),
                date(2026, 2, 17),
            )

    def test_parser_empty_for_other_day(self) -> None:
        html = CN_FIXTURE.read_text(encoding="utf-8")
        rows = parse_xueqiu_status_list(
            html, on_date=date(2026, 2, 18), market="cn"
        )
        self.assertEqual(rows, [])

    def test_parser_rejects_unsupported_market(self) -> None:
        html = CN_FIXTURE.read_text(encoding="utf-8")
        with self.assertRaises(ValueError):
            parse_xueqiu_status_list(
                html, on_date=date(2026, 2, 17), market="us"
            )


class XueqiuConnectorTests(unittest.TestCase):
    def test_map_rows_builds_community_items_cn(self) -> None:
        html = CN_FIXTURE.read_text(encoding="utf-8")
        rows = parse_xueqiu_status_list(
            html, on_date=date(2026, 2, 17), market="cn"
        )
        connector = XueqiuConnector()
        items = connector.map_rows_for_tests(
            rows,
            ticker="600519",
            market="cn",
            collected_at=datetime(2026, 2, 17, 12, 0, tzinfo=SHANGHAI),
        )
        self.assertEqual(len(items), 2)
        first = items[0]
        self.assertEqual(first.source, "xueqiu")
        self.assertEqual(first.source_type, "community")
        self.assertEqual(first.document_type, "community_post")
        self.assertEqual(first.market, MARKET_CN)
        self.assertEqual(first.tickers, ("SH600519",))
        self.assertTrue(first.title)
        self.assertTrue(first.url)
        self.assertTrue(first.published_at)

    def test_map_rows_builds_community_items_hk(self) -> None:
        html = HK_FIXTURE.read_text(encoding="utf-8")
        rows = parse_xueqiu_status_list(
            html, on_date=date(2026, 2, 17), market="hk"
        )
        connector = XueqiuConnector()
        items = connector.map_rows_for_tests(
            rows,
            ticker="0700",
            market="hk",
            collected_at=datetime(2026, 2, 17, 12, 0, tzinfo=HONG_KONG),
        )
        self.assertEqual(len(items), 2)
        first = items[0]
        self.assertEqual(first.market, MARKET_HK)
        self.assertEqual(first.tickers, ("HK00700",))

    def test_collect_is_empty_stub_cn(self) -> None:
        connector = XueqiuConnector()
        request = CollectionRequest(
            tickers=("600519",),
            start_date=date(2026, 2, 17),
            end_date=date(2026, 2, 17),
            markets={"600519": "cn"},
        )
        items = connector.collect(request)
        self.assertEqual(items, [])
        self.assertEqual(connector.status, "stub")
        self.assertTrue(connector.last_errors)
        self.assertIn("400016", connector.last_errors[0][1])

    def test_collect_is_empty_stub_hk(self) -> None:
        connector = XueqiuConnector()
        request = CollectionRequest(
            tickers=("0700.HK",),
            start_date=date(2026, 2, 17),
            end_date=date(2026, 2, 17),
            markets={"0700.HK": "hk"},
        )
        items = connector.collect(request)
        self.assertEqual(items, [])
        self.assertTrue(connector.last_errors)
        self.assertIn("HK00700", connector.last_errors[0][0])

    def test_collect_skips_other_markets(self) -> None:
        connector = XueqiuConnector()
        request = CollectionRequest(
            tickers=("BHP.AX",),
            start_date=date(2026, 2, 17),
            end_date=date(2026, 2, 17),
            markets={"BHP.AX": "au"},
        )
        items = connector.collect(request)
        self.assertEqual(items, [])
        self.assertEqual(connector.last_errors, ())

    def test_registry_registers_xueqiu(self) -> None:
        registry = create_default_registry()
        self.assertIsNotNone(registry.factory_for("xueqiu"))
        connector = registry.factory_for("xueqiu")()
        self.assertEqual(connector.name, "xueqiu")
        fields = registry.secret_fields_for("xueqiu")
        self.assertEqual(len(fields), 1)
        self.assertEqual(fields[0].env, "XUEQIU_COOKIE")
        # Missing cookie must NOT mark the source unavailable (stub is valid).
        self.assertIsNone(registry.configuration_error_for("xueqiu"))

    def test_community_soft_dedupe_uses_status_id(self) -> None:
        published = "2026-02-17T02:39:00+00:00"
        first = {
            "source": "xueqiu",
            "source_type": "community",
            "external_id": "xueqiu-2345678901",
            "ticker": "SH600519",
            "market": "cn",
            "title": "茅台三季报简评",
            "published_at": published,
            "effective_at": published,
            "raw_metadata": {"status_id": "2345678901"},
        }
        second = {
            **first,
            "external_id": "xueqiu-2345678901-dup",
        }
        self.assertEqual(dedupe_key(first), dedupe_key(second))
        self.assertEqual(
            dedupe_key(first),
            "cn:community:xueqiu:2345678901",
        )
        annotated = annotate_feed_items([first, second])
        self.assertEqual(len(annotated), 2)
        self.assertEqual(annotated[0]["also_seen_on"], ["xueqiu"])
        self.assertEqual(
            annotated[0]["also_seen_on_labels"],
            ["Xueqiu (CN/HK)"],
        )

    @patch.dict(os.environ, {"XUEQIU_COOKIE": "xq_a_token=fake_token_for_testing"})
    def test_collect_live_via_cookie(self) -> None:
        """When XUEQIU_COOKIE is set, collect should attempt the JSON API path."""
        connector = XueqiuConnector()
        with patch.object(
            connector, "_fetch_via_cookie", return_value=[]
        ):
            request = CollectionRequest(
                tickers=("600519",),
                start_date=date(2026, 2, 17),
                end_date=date(2026, 2, 17),
                markets={"600519": "cn"},
            )
            items = connector.collect(request)
            self.assertEqual(items, [])
            self.assertIn("LIVE", connector.status)

    @patch.dict(os.environ, {"XUEQIU_COOKIE": "xq_a_token=invalid_token"})
    def test_collect_cookie_rejected_falls_to_stub(self) -> None:
        """Invalid cookie → _fetch_via_cookie None → honest stub."""
        connector = XueqiuConnector()
        with patch.object(
            connector, "_fetch_via_cookie", return_value=None
        ):
            request = CollectionRequest(
                tickers=("600519",),
                start_date=date(2026, 2, 17),
                end_date=date(2026, 2, 17),
                markets={"600519": "cn"},
            )
            items = connector.collect(request)
            self.assertEqual(items, [])
            self.assertEqual(connector.status, "stub")

    @patch.dict(os.environ, {"XUEQIU_COOKIE": "   "}, clear=False)
    def test_blank_cookie_stays_stub(self) -> None:
        """Whitespace-only cookie must not enter the live path."""
        connector = XueqiuConnector()
        with patch.object(
            connector, "_fetch_via_cookie", return_value=[]
        ) as mocked:
            request = CollectionRequest(
                tickers=("600519",),
                start_date=date(2026, 2, 17),
                end_date=date(2026, 2, 17),
                markets={"600519": "cn"},
            )
            items = connector.collect(request)
            mocked.assert_not_called()
            self.assertEqual(items, [])
            self.assertEqual(connector.status, "stub")

    @patch.dict(os.environ, {"XUEQIU_COOKIE": "xq_a_token=fake"})
    def test_collect_live_filters_day_and_multi_ticker(self) -> None:
        """LIVE path aggregates all tickers (day filter covered in fetch test)."""
        connector = XueqiuConnector()
        from investment_monitor.models import InformationItem
        from datetime import timezone as tz

        def _item(ext: str, ticker: str) -> InformationItem:
            moment = datetime(2026, 2, 17, 4, 0, tzinfo=tz.utc)
            return InformationItem(
                source="xueqiu",
                source_type="community",
                external_id=ext,
                tickers=(ticker,),
                issuer=ticker,
                published_at=moment,
                title=ext,
                document_type="community_post",
                url=f"https://xueqiu.com/1/{ext}",
                collected_at=moment,
                raw_metadata={},
                market="cn",
            )

        def fake_fetch(ticker: str, market: str, *, start_date, end_date):
            code = normalize_xq_symbol(ticker, market=market)
            if code == "SH600519":
                return [_item("a", code), _item("b", code)]
            if code == "SZ000001":
                return [_item("c", code)]
            return []

        with patch.object(connector, "_fetch_via_cookie", side_effect=fake_fetch):
            request = CollectionRequest(
                tickers=("600519", "000001"),
                start_date=date(2026, 2, 17),
                end_date=date(2026, 2, 17),
                markets={"600519": "cn", "000001": "cn"},
            )
            items = connector.collect(request)
            self.assertEqual(len(items), 3)
            self.assertEqual(
                {i.external_id for i in items},
                {"a", "b", "c"},
            )
            self.assertIn("LIVE", connector.status)

    @patch.dict(os.environ, {"XUEQIU_COOKIE": "xq_a_token=fake"})
    def test_fetch_via_cookie_applies_day_filter(self) -> None:
        """JSON posts outside the requested local day are dropped."""
        connector = XueqiuConnector()
        payload = {
            "error_code": 0,
            "list": [
                {
                    "id": 111,
                    "user_id": 9,
                    "title": "in range",
                    "created_at": int(datetime(2026, 2, 17, 8, 0, tzinfo=SHANGHAI).timestamp() * 1000),
                    "description": "ok",
                },
                {
                    "id": 222,
                    "user_id": 9,
                    "title": "out of range",
                    "created_at": int(datetime(2026, 2, 16, 8, 0, tzinfo=SHANGHAI).timestamp() * 1000),
                    "description": "nope",
                },
            ],
        }

        class _Resp:
            def read(self) -> bytes:
                return json.dumps(payload).encode("utf-8")

            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

        with patch(
            "investment_monitor.sources.xueqiu.connector.urlopen",
            return_value=_Resp(),
        ):
            items = connector._fetch_via_cookie(
                "600519",
                "cn",
                start_date=date(2026, 2, 17),
                end_date=date(2026, 2, 17),
            )
        self.assertIsNotNone(items)
        assert items is not None
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0].external_id, "xueqiu-111")
        self.assertEqual(items[0].title, "in range")

    @patch.dict(os.environ, {"XUEQIU_COOKIE": "xq_a_token=fake"})
    def test_fetch_via_cookie_skips_posts_without_timestamp(self) -> None:
        """Posts without a real timestamp must be skipped, not backdated to now."""
        connector = XueqiuConnector()
        payload = {
            "error_code": 0,
            "list": [
                {"id": 333, "user_id": 9, "title": "no timestamp", "description": "skip me"},
                {
                    "id": 444,
                    "user_id": 9,
                    "title": "has timestamp",
                    "created_at": int(datetime(2026, 2, 17, 8, 0, tzinfo=SHANGHAI).timestamp() * 1000),
                    "description": "ok",
                },
            ],
        }

        class _Resp:
            def read(self) -> bytes:
                return json.dumps(payload).encode("utf-8")

            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

        with patch(
            "investment_monitor.sources.xueqiu.connector.urlopen",
            return_value=_Resp(),
        ):
            items = connector._fetch_via_cookie(
                "600519",
                "cn",
                start_date=date(2026, 2, 17),
                end_date=date(2026, 2, 17),
            )
        self.assertIsNotNone(items)
        assert items is not None
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0].external_id, "xueqiu-444")
