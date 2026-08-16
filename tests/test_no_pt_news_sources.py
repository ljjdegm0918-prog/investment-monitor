"""NO/PT news source tests."""

from datetime import date
import unittest

from investment_monitor.models import CollectionRequest
from investment_monitor.registry import SOURCE_MARKETS, create_default_registry
from investment_monitor.sources.no_news import (
    GoogleNoNewsConnector,
    YahooNoNewsConnector,
)
from investment_monitor.sources.no_news.symbols import no_yahoo_symbol
from investment_monitor.sources.pt_news import (
    GooglePtNewsConnector,
    YahooPtNewsConnector,
)
from investment_monitor.sources.pt_news.symbols import pt_yahoo_symbol


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


class NoPtNewsSourceTests(unittest.TestCase):
    def test_yahoo_symbols_use_locked_suffixes(self):
        self.assertEqual(no_yahoo_symbol("EQNR"), "EQNR.OL")
        self.assertEqual(pt_yahoo_symbol("EDP"), "EDP.LS")

    def test_yahoo_connectors_skip_foreign_markets_without_http(self):
        for connector_cls, ticker, market in (
            (YahooNoNewsConnector, "EQNR", "no"),
            (YahooPtNewsConnector, "EDP", "pt"),
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
            client2 = FakeYahooClient()
            connector2 = connector_cls(client=client2)
            request2 = CollectionRequest(
                tickers=(ticker,),
                start_date=date(2026, 8, 1),
                end_date=date(2026, 8, 1),
                markets={ticker: market},
            )
            self.assertEqual(connector2.collect(request2), [])
            self.assertTrue(client2.calls)

    def test_google_connectors_skip_foreign_markets_without_http(self):
        for connector_cls in (GoogleNoNewsConnector, GooglePtNewsConnector):
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

    def test_registry_scopes(self):
        self.assertEqual(SOURCE_MARKETS["yahoo_no"], "no")
        self.assertEqual(SOURCE_MARKETS["google_news_no"], "no")
        self.assertEqual(SOURCE_MARKETS["yahoo_pt"], "pt")
        self.assertEqual(SOURCE_MARKETS["google_news_pt"], "pt")
        registry = create_default_registry()
        for name in ("yahoo_no", "google_news_no", "yahoo_pt", "google_news_pt"):
            self.assertIn(name, registry.registered_names)


if __name__ == "__main__":
    unittest.main()
