"""Hungary stub/news/dedupe tests."""

from datetime import date
import unittest

from investment_monitor.dedupe import annotate_feed_items, dedupe_key
from investment_monitor.models import CollectionRequest
from investment_monitor.registry import SOURCE_MARKETS, create_default_registry
from investment_monitor.sources.bse_hu_announcements import (
    BseHuAnnouncementsConnector,
)
from investment_monitor.sources.hu_news import (
    GoogleHuNewsConnector,
    YahooHuNewsConnector,
)
from investment_monitor.sources.hu_news.symbols import hu_yahoo_symbol


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


class HungaryTests(unittest.TestCase):
    def test_disclosure_connector_is_honest_stub(self):
        connector = BseHuAnnouncementsConnector()
        self.assertEqual(connector.collect(CollectionRequest(
            tickers=("OTP",), start_date=date(2026, 8, 1),
            end_date=date(2026, 8, 1), markets={"OTP": "hu"},
        )), [])
        self.assertEqual(connector.last_collection_status, "stub")

    def test_yahoo_symbol_and_foreign_skip(self):
        self.assertEqual(hu_yahoo_symbol("OTP"), "OTP.BU")
        client = FakeYahooClient()
        connector = YahooHuNewsConnector(client=client)
        request = CollectionRequest(
            tickers=("AAPL",), start_date=date(2026, 8, 1),
            end_date=date(2026, 8, 1), markets={"AAPL": "us"},
        )
        self.assertEqual(connector.collect(request), [])
        self.assertEqual(client.calls, [])

    def test_google_foreign_skip(self):
        client = FakeGoogleClient()
        connector = GoogleHuNewsConnector(client=client)
        request = CollectionRequest(
            tickers=("AAPL",), start_date=date(2026, 8, 1),
            end_date=date(2026, 8, 1), markets={"AAPL": "us"},
        )
        self.assertEqual(connector.collect(request), [])
        self.assertEqual(client.calls, [])

    def test_registry_scopes_and_names_not_india_bse(self):
        self.assertEqual(SOURCE_MARKETS["bse_hu_announcements"], "hu")
        self.assertEqual(SOURCE_MARKETS["yahoo_hu"], "hu")
        self.assertEqual(SOURCE_MARKETS["google_news_hu"], "hu")
        registry = create_default_registry()
        for name in ("bse_hu_announcements", "yahoo_hu", "google_news_hu"):
            self.assertIn(name, registry.registered_names)
        # 印度 BSE 没有独立连接器，不得与匈牙利 BSE 命名混淆
        self.assertNotIn("bse_announcements", registry.registered_names)

    def test_dedupe_news_pairs_and_stub_filing_never_annotates(self):
        annotated = annotate_feed_items([
            {
                "source": "yahoo_hu", "source_type": "news", "market": "hu",
                "ticker": "OTP", "title": "Results", "external_id": "y1",
                "published_at": "2026-08-14T12:00:00+00:00",
            },
            {
                "source": "google_news_hu", "source_type": "news", "market": "hu",
                "ticker": "OTP", "title": "Results", "external_id": "g1",
                "published_at": "2026-08-14T12:00:00+00:00",
            },
        ])
        self.assertEqual(annotated[0]["also_seen_on"], ["google_news_hu"])
        filing = {
            "source": "bse_hu_announcements", "source_type": "regulatory_filing",
            "market": "hu", "ticker": "OTP", "title": "x",
            "external_id": "hu:1", "published_at": "2026-08-14T12:00:00+00:00",
        }
        self.assertIsNone(dedupe_key(filing))


if __name__ == "__main__":
    unittest.main()
