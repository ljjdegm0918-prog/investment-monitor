"""Austria official disclosure, news, and dedupe tests."""

from datetime import date, datetime, timezone
import unittest

from investment_monitor.dedupe import annotate_feed_items, dedupe_key
from investment_monitor.models import CollectionRequest
from investment_monitor.registry import SOURCE_MARKETS, create_default_registry
from investment_monitor.sources.at_news import (
    GoogleAtNewsConnector,
    YahooAtNewsConnector,
)
from investment_monitor.sources.at_news.symbols import at_yahoo_symbol
from investment_monitor.sources.wiener_boerse_news import (
    WienerBoerseNewsConnector,
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


class FakeDisclosureClient:
    timezone = timezone.utc
    def fetch(self, start_date, end_date):
        return [{"external_id": "at:1", "ticker": "VOE", "issuer": "VOE",
                 "published_at": datetime(2026, 8, 1, 9, tzinfo=timezone.utc),
                 "title": "Results", "document_type": "Ad-hoc News",
                 "url": "https://www.wienerborse.at/news/1", "raw_payload": {"id": 1}}]


class AustriaTests(unittest.TestCase):
    def test_disclosure_connector_maps_official_record(self):
        connector = WienerBoerseNewsConnector(client=FakeDisclosureClient(), universe={})
        items = connector.collect(CollectionRequest(
            tickers=("VOE",), start_date=date(2026, 8, 1),
            end_date=date(2026, 8, 1), markets={"VOE": "at"},
        ))
        self.assertEqual(len(items), 1)
        self.assertEqual(connector.last_collection_status, "success")

    def test_yahoo_symbol_and_foreign_skip(self):
        self.assertEqual(at_yahoo_symbol("VOE"), "VOE.VI")
        client = FakeYahooClient()
        connector = YahooAtNewsConnector(client=client)
        request = CollectionRequest(
            tickers=("AAPL",), start_date=date(2026, 8, 1),
            end_date=date(2026, 8, 1), markets={"AAPL": "us"},
        )
        self.assertEqual(connector.collect(request), [])
        self.assertEqual(client.calls, [])

    def test_google_foreign_skip(self):
        client = FakeGoogleClient()
        connector = GoogleAtNewsConnector(client=client)
        request = CollectionRequest(
            tickers=("AAPL",), start_date=date(2026, 8, 1),
            end_date=date(2026, 8, 1), markets={"AAPL": "us"},
        )
        self.assertEqual(connector.collect(request), [])
        self.assertEqual(client.calls, [])

    def test_registry_scopes(self):
        self.assertEqual(SOURCE_MARKETS["wiener_boerse_news"], "at")
        self.assertEqual(SOURCE_MARKETS["yahoo_at"], "at")
        self.assertEqual(SOURCE_MARKETS["google_news_at"], "at")
        registry = create_default_registry()
        for name in ("wiener_boerse_news", "yahoo_at", "google_news_at"):
            self.assertIn(name, registry.registered_names)

    def test_dedupe_news_pairs_and_official_filing_uses_native_id(self):
        annotated = annotate_feed_items([
            {
                "source": "yahoo_at", "source_type": "news", "market": "at",
                "ticker": "VOE", "title": "Results", "external_id": "y1",
                "published_at": "2026-08-14T09:00:00+00:00",
            },
            {
                "source": "google_news_at", "source_type": "news", "market": "at",
                "ticker": "VOE", "title": "Results", "external_id": "g1",
                "published_at": "2026-08-14T09:00:00+00:00",
            },
        ])
        self.assertEqual(len(annotated), 2)
        self.assertEqual(annotated[0]["also_seen_on"], ["google_news_at"])
        filing = {
            "source": "wiener_boerse_news", "source_type": "regulatory_filing",
            "market": "at", "ticker": "VOE", "title": "x",
            "external_id": "at:1", "published_at": "2026-08-14T09:00:00+00:00",
        }
        self.assertEqual(dedupe_key(filing), "at:filing:wiener:at:1")


if __name__ == "__main__":
    unittest.main()
