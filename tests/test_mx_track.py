"""Mexico stub/news/dedupe tests."""

from datetime import date, datetime, timezone
import unittest

from investment_monitor.dedupe import annotate_feed_items, dedupe_key
from investment_monitor.models import CollectionRequest
from investment_monitor.registry import SOURCE_MARKETS, create_default_registry
from investment_monitor.sources.bmv_relevant_events import (
    BmvRelevantEventsConnector,
)
from investment_monitor.sources.mx_news import (
    GoogleMxNewsConnector,
    YahooMxNewsConnector,
)
from investment_monitor.sources.mx_news.symbols import mx_yahoo_symbol


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


class FakeDisclosureClient:
    timezone = timezone.utc
    def fetch(self, start_date, end_date):
        return [{"external_id": "mx:1", "ticker": "WALMEX", "issuer": "WALMEX",
                 "published_at": datetime(2026, 8, 1, 9, tzinfo=timezone.utc),
                 "title": "Relevant event", "document_type": "evento relevante",
                 "url": "https://www.bmv.com.mx/docs-pub/event.pdf", "raw_payload": {"id": 1}}]


class MexicoTests(unittest.TestCase):
    def test_disclosure_connector_maps_official_record(self):
        connector = BmvRelevantEventsConnector(client=FakeDisclosureClient(), universe={})
        items = connector.collect(CollectionRequest(
            tickers=("WALMEX",), start_date=date(2026, 8, 1),
            end_date=date(2026, 8, 1), markets={"WALMEX": "mx"},
        ))
        self.assertEqual(len(items), 1)
        self.assertEqual(connector.last_collection_status, "success")

    def test_yahoo_symbol_and_foreign_skip(self):
        self.assertEqual(mx_yahoo_symbol("WALMEX"), "WALMEX.MX")
        client = FakeYahooClient()
        connector = YahooMxNewsConnector(client=client)
        request = CollectionRequest(
            tickers=("AAPL",), start_date=date(2026, 8, 1),
            end_date=date(2026, 8, 1), markets={"AAPL": "us"},
        )
        self.assertEqual(connector.collect(request), [])
        self.assertEqual(client.calls, [])

    def test_google_foreign_skip(self):
        client = FakeGoogleClient()
        connector = GoogleMxNewsConnector(client=client)
        request = CollectionRequest(
            tickers=("AAPL",), start_date=date(2026, 8, 1),
            end_date=date(2026, 8, 1), markets={"AAPL": "us"},
        )
        self.assertEqual(connector.collect(request), [])
        self.assertEqual(client.calls, [])

    def test_registry_scopes(self):
        self.assertEqual(SOURCE_MARKETS["bmv_relevant_events"], "mx")
        self.assertEqual(SOURCE_MARKETS["yahoo_mx"], "mx")
        self.assertEqual(SOURCE_MARKETS["google_news_mx"], "mx")
        registry = create_default_registry()
        for name in ("bmv_relevant_events", "yahoo_mx", "google_news_mx"):
            self.assertIn(name, registry.registered_names)

    def test_dedupe_news_pairs_and_stub_filing_never_annotates(self):
        annotated = annotate_feed_items([
            {
                "source": "yahoo_mx", "source_type": "news", "market": "mx",
                "ticker": "WALMEX", "title": "Results", "external_id": "y1",
                "published_at": "2026-08-14T15:00:00+00:00",
            },
            {
                "source": "google_news_mx", "source_type": "news", "market": "mx",
                "ticker": "WALMEX", "title": "Results", "external_id": "g1",
                "published_at": "2026-08-14T15:00:00+00:00",
            },
        ])
        self.assertEqual(annotated[0]["also_seen_on"], ["google_news_mx"])
        filing = {
            "source": "bmv_relevant_events", "source_type": "regulatory_filing",
            "market": "mx", "ticker": "WALMEX", "title": "x",
            "external_id": "mx:1", "published_at": "2026-08-14T15:00:00+00:00",
        }
        self.assertIsNone(dedupe_key(filing))


if __name__ == "__main__":
    unittest.main()
