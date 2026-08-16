"""Israel stub/news/dedupe tests."""

from datetime import date
import unittest

from investment_monitor.dedupe import annotate_feed_items, dedupe_key
from investment_monitor.models import CollectionRequest
from investment_monitor.registry import SOURCE_MARKETS, create_default_registry
from investment_monitor.sources.il_news import (
    GoogleIlNewsConnector,
    YahooIlNewsConnector,
)
from investment_monitor.sources.il_news.symbols import il_yahoo_symbol
from investment_monitor.sources.maya_announcements import (
    MayaAnnouncementsConnector,
)


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


class IsraelTests(unittest.TestCase):
    def test_disclosure_connector_is_honest_stub(self):
        connector = MayaAnnouncementsConnector()
        self.assertEqual(connector.collect(CollectionRequest(
            tickers=("TEVA",), start_date=date(2026, 8, 1),
            end_date=date(2026, 8, 1), markets={"TEVA": "il"},
        )), [])
        self.assertEqual(connector.last_collection_status, "stub")

    def test_yahoo_symbol_and_foreign_skip(self):
        self.assertEqual(il_yahoo_symbol("TEVA"), "TEVA.TA")
        client = FakeYahooClient()
        connector = YahooIlNewsConnector(client=client)
        request = CollectionRequest(
            tickers=("AAPL",), start_date=date(2026, 8, 1),
            end_date=date(2026, 8, 1), markets={"AAPL": "us"},
        )
        self.assertEqual(connector.collect(request), [])
        self.assertEqual(client.calls, [])

    def test_google_foreign_skip(self):
        client = FakeGoogleClient()
        connector = GoogleIlNewsConnector(client=client)
        request = CollectionRequest(
            tickers=("AAPL",), start_date=date(2026, 8, 1),
            end_date=date(2026, 8, 1), markets={"AAPL": "us"},
        )
        self.assertEqual(connector.collect(request), [])
        self.assertEqual(client.calls, [])

    def test_registry_scopes(self):
        self.assertEqual(SOURCE_MARKETS["maya_announcements"], "il")
        self.assertEqual(SOURCE_MARKETS["yahoo_il"], "il")
        self.assertEqual(SOURCE_MARKETS["google_news_il"], "il")
        registry = create_default_registry()
        for name in ("maya_announcements", "yahoo_il", "google_news_il"):
            self.assertIn(name, registry.registered_names)

    def test_dedupe_news_pairs_and_stub_filing_never_annotates(self):
        annotated = annotate_feed_items([
            {
                "source": "yahoo_il", "source_type": "news", "market": "il",
                "ticker": "TEVA", "title": "Results", "external_id": "y1",
                "published_at": "2026-08-14T12:00:00+00:00",
            },
            {
                "source": "google_news_il", "source_type": "news", "market": "il",
                "ticker": "TEVA", "title": "Results", "external_id": "g1",
                "published_at": "2026-08-14T12:00:00+00:00",
            },
        ])
        self.assertEqual(annotated[0]["also_seen_on"], ["google_news_il"])
        filing = {
            "source": "maya_announcements", "source_type": "regulatory_filing",
            "market": "il", "ticker": "TEVA", "title": "x",
            "external_id": "il:1", "published_at": "2026-08-14T12:00:00+00:00",
        }
        self.assertIsNone(dedupe_key(filing))


if __name__ == "__main__":
    unittest.main()
