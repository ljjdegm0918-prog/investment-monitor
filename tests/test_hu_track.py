"""Hungary stub/news/dedupe tests."""

from datetime import date, datetime, timezone
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


class FakeDisclosureClient:
    timezone = timezone.utc
    last_fetch_truncated = False
    last_pages_read = 1
    def fetch(self, start_date, end_date):
        return [{"external_id": "hu:1", "ticker": "OTP", "issuer": "OTP Bank Plc.",
                 "published_at": datetime(2026, 8, 1, 9, tzinfo=timezone.utc),
                 "title": "Results", "document_type": "announcement",
                 "url": "https://www.bse.hu/site/newkib/en/1", "raw_payload": {"id": 1}}]


class FakeUnmatchedDisclosureClient(FakeDisclosureClient):
    def fetch(self, start_date, end_date):
        return [{"external_id": "hu:pending", "issuer": "Unknown Hungarian Plc.",
                 "published_at": datetime(2026, 8, 1, 9, tzinfo=timezone.utc),
                 "title": "Issuer announcement", "document_type": "announcement",
                 "url": "https://www.bse.hu/site/newkib/en/pending",
                 "raw_payload": {"id": "pending"}}]


class FakeTwoKnownIssuersClient(FakeDisclosureClient):
    def fetch(self, start_date, end_date):
        return [
            {"external_id": "hu:otp", "issuer": "OTP Bank Plc.",
             "published_at": datetime(2026, 8, 1, 9, tzinfo=timezone.utc),
             "title": "OTP results", "document_type": "announcement",
             "url": "https://www.bse.hu/site/newkib/en/otp", "raw_payload": {"id": "otp"}},
            {"external_id": "hu:mol", "issuer": "MOL Plc.",
             "published_at": datetime(2026, 8, 1, 10, tzinfo=timezone.utc),
             "title": "MOL results", "document_type": "announcement",
             "url": "https://www.bse.hu/site/newkib/en/mol", "raw_payload": {"id": "mol"}},
        ]


class HungaryTests(unittest.TestCase):
    def test_disclosure_connector_maps_official_record(self):
        connector = BseHuAnnouncementsConnector(client=FakeDisclosureClient(), universe={})
        items = connector.collect(CollectionRequest(
            tickers=("OTP",), start_date=date(2026, 8, 1),
            end_date=date(2026, 8, 1), markets={"OTP": "hu"},
        ))
        self.assertEqual(len(items), 1)
        self.assertEqual(connector.last_collection_status, "success")

    def test_disclosure_page_limit_is_reported_partial(self):
        client = FakeDisclosureClient()
        client.last_fetch_truncated = True
        client.last_pages_read = 200
        connector = BseHuAnnouncementsConnector(client=client, universe={})
        items = connector.collect(CollectionRequest(
            tickers=("OTP",), start_date=date(2026, 8, 1),
            end_date=date(2026, 8, 1), markets={"OTP": "hu"},
        ))
        self.assertEqual(len(items), 1)
        self.assertEqual(connector.last_collection_status, "partial")
        self.assertIn("200 page limit", connector.last_errors[0][1])

    def test_market_wide_connector_preserves_unmatched_official_record(self):
        connector = BseHuAnnouncementsConnector(
            client=FakeUnmatchedDisclosureClient(),
            universe={"OTP": {"name": "OTP Bank Plc."}},
        )
        items = connector.collect(CollectionRequest(
            tickers=("OTP",), start_date=date(2026, 8, 1),
            end_date=date(2026, 8, 1), markets={"OTP": "hu"},
        ))

        self.assertTrue(connector.source_wide_collection)
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0].tickers, ())
        self.assertEqual(items[0].raw_metadata["match_status"], "pending")
        self.assertEqual(connector.last_collection_status, "partial")
        self.assertIn("pending issuer matching", connector.last_errors[0][1])

    def test_market_wide_connector_resolves_known_issuer_outside_request(self):
        connector = BseHuAnnouncementsConnector(
            client=FakeTwoKnownIssuersClient(),
            universe={
                "OTP": {"name": "OTP Bank Plc.", "isin": "HU0000061726"},
                "HU0000061726": {"name": "OTP Bank Plc.", "isin": "HU0000061726"},
                "MOL": {"name": "MOL Plc.", "isin": "HU0000153937"},
                "HU0000153937": {"name": "MOL Plc.", "isin": "HU0000153937"},
            },
        )
        items = connector.collect(CollectionRequest(
            tickers=("OTP",), start_date=date(2026, 8, 1),
            end_date=date(2026, 8, 1), markets={"OTP": "hu"},
        ))

        self.assertEqual({item.tickers for item in items}, {("OTP",), ("MOL",)})
        self.assertEqual(connector.last_unmatched_records, 0)
        self.assertEqual(connector.last_collection_status, "success")

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

    def test_registry_scopes_and_names_keep_india_bse_distinct(self):
        self.assertEqual(SOURCE_MARKETS["bse_hu_announcements"], "hu")
        self.assertEqual(SOURCE_MARKETS["yahoo_hu"], "hu")
        self.assertEqual(SOURCE_MARKETS["google_news_hu"], "hu")
        registry = create_default_registry()
        for name in ("bse_hu_announcements", "yahoo_hu", "google_news_hu"):
            self.assertIn(name, registry.registered_names)
        # 印度 BSE 使用明确名称，不能与匈牙利 BSE 混淆。
        self.assertIn("bse_india_announcements", registry.registered_names)
        self.assertEqual(SOURCE_MARKETS["bse_india_announcements"], "in")

    def test_dedupe_news_pairs_and_hu_filing_has_source_scoped_key(self):
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
        self.assertEqual(
            dedupe_key(filing),
            "hu:filing:bse_hu_announcements:hu:1",
        )


if __name__ == "__main__":
    unittest.main()
