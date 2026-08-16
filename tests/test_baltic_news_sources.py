"""Baltic Yahoo/Google news source tests."""

from datetime import date
import unittest

from investment_monitor.models import CollectionRequest
from investment_monitor.registry import SOURCE_MARKETS, create_default_registry
from investment_monitor.sources.ee_news import (
    GoogleEeNewsConnector,
    YahooEeNewsConnector,
)
from investment_monitor.sources.ee_news.symbols import ee_yahoo_symbol
from investment_monitor.sources.lv_news import (
    GoogleLvNewsConnector,
    YahooLvNewsConnector,
)
from investment_monitor.sources.lv_news.symbols import lv_yahoo_symbol
from investment_monitor.sources.lt_news import (
    GoogleLtNewsConnector,
    YahooLtNewsConnector,
)
from investment_monitor.sources.lt_news.symbols import lt_yahoo_symbol


class FakeYahooClient:
    def __init__(self):
        self.calls = []

    def fetch_news(self, symbol, start_date, end_date, lang=None):
        self.calls.append((symbol, start_date, end_date, lang))
        return []


class FakeGoogleClient:
    def __init__(self):
        self.calls = []

    def fetch_news(self, symbol, start_date, end_date):
        self.calls.append((symbol, start_date, end_date))
        return []


class BalticNewsSourceTests(unittest.TestCase):
    def test_yahoo_symbols_use_locked_suffixes(self):
        self.assertEqual(ee_yahoo_symbol("TAL1T"), "TAL1T.TL")
        self.assertEqual(lv_yahoo_symbol("SAF1R"), "SAF1R.RG")
        self.assertEqual(lt_yahoo_symbol("TEL1L"), "TEL1L.VL")

    def test_yahoo_connectors_skip_foreign_markets_without_http(self):
        for connector_cls, ticker, market in (
            (YahooEeNewsConnector, "TAL1T", "ee"),
            (YahooLvNewsConnector, "SAF1R", "lv"),
            (YahooLtNewsConnector, "TEL1L", "lt"),
        ):
            client = FakeYahooClient()
            connector = connector_cls(client=client)
            request = CollectionRequest(
                tickers=("AAPL",),
                start_date=date(2026, 8, 1),
                end_date=date(2026, 8, 1),
                markets={"AAPL": "us"},
            )
            self.assertEqual(connector.collect(request), [])
            self.assertEqual(client.calls, [])
            # 本国市场请求走真实 symbol
            client2 = FakeYahooClient()
            connector2 = connector_cls(client=client2)
            request2 = CollectionRequest(
                tickers=(ticker,),
                start_date=date(2026, 8, 1),
                end_date=date(2026, 8, 1),
                markets={ticker: market},
            )
            items = connector2.collect(request2)
            self.assertEqual(items, [])
            self.assertTrue(client2.calls)

    def test_google_connectors_skip_foreign_markets_without_http(self):
        for connector_cls in (
            GoogleEeNewsConnector,
            GoogleLvNewsConnector,
            GoogleLtNewsConnector,
        ):
            client = FakeGoogleClient()
            connector = connector_cls(client=client)
            request = CollectionRequest(
                tickers=("AAPL",),
                start_date=date(2026, 8, 1),
                end_date=date(2026, 8, 1),
                markets={"AAPL": "us"},
            )
            self.assertEqual(connector.collect(request), [])
            self.assertEqual(client.calls, [])

    def test_registry_scopes_baltic_sources(self):
        registry = create_default_registry()
        for name in (
            "nasdaq_baltic_news",
            "yahoo_ee",
            "google_news_ee",
            "yahoo_lv",
            "google_news_lv",
            "yahoo_lt",
            "google_news_lt",
        ):
            self.assertIn(name, registry.registered_names)
        self.assertEqual(SOURCE_MARKETS["yahoo_ee"], "ee")
        self.assertEqual(SOURCE_MARKETS["yahoo_lv"], "lv")
        self.assertEqual(SOURCE_MARKETS["yahoo_lt"], "lt")
        self.assertEqual(
            SOURCE_MARKETS["nasdaq_baltic_news"], frozenset({"ee", "lv", "lt"})
        )


if __name__ == "__main__":
    unittest.main()
