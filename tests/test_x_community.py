"""Unit tests for the X (Twitter) community connector.

The connector now has an official X API v2 path behind ``X_BEARER_TOKEN``.
Without that token it must stay honest and report unavailable instead of
pretending to be live.
"""

from __future__ import annotations

from datetime import date
import os
import unittest
from unittest.mock import patch

from investment_monitor import CollectionRequest, create_default_registry
from investment_monitor.connectors.base import ConnectorUnavailableError
from investment_monitor.sources.x_community import XCommunityConnector


class XCommunityTests(unittest.TestCase):
    def test_connector_attributes_and_secret_field(self) -> None:
        self.assertEqual(XCommunityConnector.name, "x_community")
        self.assertEqual(XCommunityConnector.provider, "X")
        self.assertEqual(XCommunityConnector.status, "live")
        self.assertEqual(XCommunityConnector.secret_fields[0].env, "X_BEARER_TOKEN")

    def test_configuration_error_is_truthful_without_token(self) -> None:
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("X_BEARER_TOKEN", None)

            self.assertIsNotNone(XCommunityConnector.configuration_error())
            with self.assertRaises(ConnectorUnavailableError):
                XCommunityConnector.from_environment()

            registry = create_default_registry()
            self.assertEqual(
                registry.secret_fields_for("x_community")[0].env,
                "X_BEARER_TOKEN",
            )
            self.assertEqual(
                registry.configuration_error_for("x_community"),
                "X_BEARER_TOKEN is not configured; X is not connected.",
            )

    def test_collect_maps_official_api_results(self) -> None:
        payload = {
            "data": [
                {
                    "id": "200",
                    "created_at": "2026-08-11T13:01:00Z",
                    "text": "$AAPL prints after-hours strength",
                    "entities": {"cashtags": [{"tag": "AAPL"}]},
                    "attachments": {"community_id": "98765"},
                },
                {
                    "id": "201",
                    "created_at": "2026-08-12T05:00:00Z",
                    "text": "$AAPL older day item",
                    "entities": {"cashtags": [{"tag": "AAPL"}]},
                },
            ],
            "includes": {"communities": [{"id": "98765"}]},
        }

        def fake_fetch(url: str):
            self.assertIn("search/recent", url)
            self.assertIn("query=%24AAPL+-is%3Aretweet", url)
            self.assertIn("start_time=2026-08-11T04%3A00%3A00Z", url)
            self.assertIn("end_time=2026-08-12T03%3A59%3A59Z", url)
            return payload

        connector = XCommunityConnector(
            bearer_token="test-token",
            fetch_json=fake_fetch,
        )
        request = CollectionRequest(
            tickers=("aapl",),
            start_date=date(2026, 8, 11),
            end_date=date(2026, 8, 11),
            markets={"aapl": "us"},
        )

        items = connector.collect(request)

        self.assertEqual(len(items), 1)
        item = items[0]
        self.assertEqual(item.external_id, "x-200")
        self.assertEqual(item.source, "x_community")
        self.assertEqual(item.tickers, ("AAPL",))
        self.assertEqual(item.document_type, "community_post")
        self.assertEqual(item.url, "https://x.com/i/web/status/200")
        self.assertEqual(item.raw_metadata["deeplink"], "https://x.com/i/web/status/200")
        self.assertEqual(item.raw_metadata["community_id"], "98765")
        self.assertEqual(item.raw_metadata["cashtags"], ("AAPL",))
        self.assertEqual(item.summary, "$AAPL prints after-hours strength")
        self.assertEqual(connector.last_errors, ())

    def test_collect_skips_non_us(self) -> None:
        connector = XCommunityConnector(bearer_token="test-token", fetch_json=lambda url: {"data": []})
        request = CollectionRequest(
            tickers=("0700",),
            start_date=date(2026, 8, 11),
            end_date=date(2026, 8, 11),
            markets={"0700": "hk"},
        )

        items = connector.collect(request)

        self.assertEqual(items, [])
        self.assertEqual(connector.last_errors, ())


if __name__ == "__main__":
    unittest.main()
