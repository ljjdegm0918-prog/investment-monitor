"""Unit tests for the X (Twitter) community connector — honest stub.

Mirrors the ``yellowbrick`` / ``xueqiu`` registered-stub tests: the spike
(2026-08-11, see ``tests/fixtures/x_community/probe_public.py``) showed X has
no stable public login-free surface for ticker discovery — search, Communities
and profile timelines are client-rendered SPA shells behind a login wall for
stdlib urllib, every Nitter mirror is dead or bot-walled, and the only
key-free endpoints (single status page SSR, oEmbed, undocumented syndication
``tweet-result``) require a known tweet id/URL in advance and cannot
enumerate or search by ticker. The official X API v2 search/recent endpoint
needs a paid Bearer/OAuth2 key. So ``collect()`` never hits the network and
returns ``[]`` with honest ``last_errors``. No live network is used in these
tests.
"""

from __future__ import annotations

import unittest
from datetime import date

from investment_monitor.models import MARKET_US, CollectionRequest
from investment_monitor.registry import create_default_registry
from investment_monitor.sources.x_community import XCommunityConnector


class XCommunityStubTests(unittest.TestCase):
    def test_connector_attributes(self) -> None:
        connector = XCommunityConnector()
        self.assertEqual(connector.name, "x_community")
        self.assertEqual(connector.provider, "X")
        self.assertEqual(connector.status, "stub")

    def test_collect_is_empty_stub(self) -> None:
        connector = XCommunityConnector()
        request = CollectionRequest(
            tickers=("AAPL",),
            start_date=date(2026, 8, 11),
            end_date=date(2026, 8, 11),
            markets={"AAPL": "us"},
        )
        items = connector.collect(request)
        self.assertEqual(items, [])
        self.assertEqual(connector.status, "stub")
        self.assertTrue(connector.last_errors)
        self.assertEqual(connector.last_errors[0][0], "AAPL")
        message = connector.last_errors[0][1]
        self.assertIn("x.com/search", message)
        self.assertIn("login wall", message)
        self.assertIn("Nitter", message)
        self.assertIn("Bearer", message)

    def test_collect_records_each_us_ticker(self) -> None:
        connector = XCommunityConnector()
        request = CollectionRequest(
            tickers=("aapl", "NVDA"),
            start_date=date(2026, 8, 11),
            end_date=date(2026, 8, 11),
            markets={"aapl": "us", "NVDA": "us"},
        )
        items = connector.collect(request)
        self.assertEqual(items, [])
        self.assertEqual(len(connector.last_errors), 2)
        self.assertEqual(
            [note[0] for note in connector.last_errors],
            ["AAPL", "NVDA"],
        )

    def test_collect_skips_non_us(self) -> None:
        connector = XCommunityConnector()
        request = CollectionRequest(
            tickers=("0700",),
            start_date=date(2026, 8, 11),
            end_date=date(2026, 8, 11),
            markets={"0700": "hk"},
        )
        items = connector.collect(request)
        self.assertEqual(items, [])
        self.assertEqual(connector.last_errors, ())

    def test_registry_registers_x_community(self) -> None:
        registry = create_default_registry()
        self.assertIsNotNone(registry.factory_for("x_community"))
        connector = registry.factory_for("x_community")()
        self.assertEqual(connector.name, "x_community")
        self.assertEqual(connector.status, "stub")

    def test_collect_mixed_us_and_other(self) -> None:
        # Only US tickers get honest stub notes; other markets are skipped
        # without a network attempt or failure record.
        connector = XCommunityConnector()
        request = CollectionRequest(
            tickers=("AAPL", "0700"),
            start_date=date(2026, 8, 11),
            end_date=date(2026, 8, 11),
            markets={"AAPL": "us", "0700": "hk"},
        )
        items = connector.collect(request)
        self.assertEqual(items, [])
        self.assertEqual(len(connector.last_errors), 1)
        self.assertEqual(connector.last_errors[0][0], "AAPL")


if __name__ == "__main__":
    unittest.main()
