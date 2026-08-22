"""NO/PT official disclosure connector tests."""

from datetime import date, datetime, timezone
import unittest

from investment_monitor.models import CollectionRequest
from investment_monitor.registry import SOURCE_MARKETS, create_default_registry
from investment_monitor.sources.no_pt_disclosures import (
    EuronextLisbonNewsConnector,
    NewswebNoConnector,
)


class FakeClient:
    timezone = timezone.utc

    def __init__(self, ticker):
        self.ticker = ticker
        self.calls = []

    def fetch(self, start_date, end_date):
        self.calls.append((start_date, end_date))
        return [{
            "external_id": "official:1", "ticker": self.ticker,
            "issuer": self.ticker, "title": "Annual results",
            "published_at": datetime(2026, 8, 1, 10, tzinfo=timezone.utc),
            "published_at_raw": "2026-08-01T10:00:00Z",
            "published_timezone": "UTC", "document_type": "results",
            "url": "https://official.example/1", "retrieval_url": "https://official.example/feed",
            "raw_payload": {"id": 1}, "raw_payload_format": "json",
        }]


class NoPtDisclosureTests(unittest.TestCase):
    def test_connectors_map_official_records(self):
        for connector, market in (
            (NewswebNoConnector(client=FakeClient("X"), universe={}), "no"),
            (EuronextLisbonNewsConnector(client=FakeClient("X"), universe={}), "pt"),
        ):
            items = connector.collect(CollectionRequest(
                tickers=("X",), start_date=date(2026, 8, 1),
                end_date=date(2026, 8, 1), markets={"X": market},
            ))
            self.assertEqual(len(items), 1)
            self.assertEqual(items[0].market, market)
            self.assertEqual(connector.last_collection_status, "success")
            self.assertEqual(connector.last_errors, ())

    def test_registry_scopes(self):
        self.assertEqual(SOURCE_MARKETS["newsweb_no"], "no")
        self.assertEqual(SOURCE_MARKETS["euronext_lisbon_news"], "pt")
        registry = create_default_registry()
        self.assertIn("newsweb_no", registry.registered_names)
        self.assertIn("euronext_lisbon_news", registry.registered_names)

    def test_source_wide_unmatched_record_is_preserved_as_pending(self):
        connector = NewswebNoConnector(client=FakeClient("UNKNOWN"), universe={})
        items = connector.collect(CollectionRequest(
            tickers=("EQNR",), start_date=date(2026, 8, 1),
            end_date=date(2026, 8, 1), markets={"EQNR": "no"},
        ))
        self.assertTrue(connector.source_wide_collection)
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0].tickers, ())
        self.assertEqual(items[0].raw_metadata["match_status"], "pending")
        self.assertEqual(items[0].raw_metadata["identity_candidates"]["ticker"], "UNKNOWN")
        self.assertEqual(connector.last_unmatched_records, 1)

    def test_client_ticker_errors_are_recorded_without_a_separate_partial_state(self):
        client = FakeClient("X")
        client.last_ticker_errors = (("BAD", "official identity unresolved"),)
        connector = NewswebNoConnector(client=client, universe={})
        items = connector.collect(CollectionRequest(
            tickers=("X",), start_date=date(2026, 8, 1),
            end_date=date(2026, 8, 1), markets={"X": "no"},
        ))
        self.assertEqual(len(items), 1)
        self.assertEqual(connector.last_collection_status, "success")
        self.assertEqual(connector.last_errors, client.last_ticker_errors)


if __name__ == "__main__":
    unittest.main()
