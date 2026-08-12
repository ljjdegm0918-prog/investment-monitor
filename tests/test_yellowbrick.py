"""Unit tests for the Yellowbrick Investing (US) connector — honest stub.

Mirrors the ``hotcopper_au`` / ``xueqiu`` registered-stub tests: the spike
(2026-08-11) showed Yellowbrick Investing has no public login-free surface
(``ybrick.co`` dead, ``joinyellowbrick.com`` marketing-only with all content
paths 404, Substack is a waitlist), so ``collect()`` never hits the network
and returns ``[]`` with honest ``last_errors``. ``yellowbrick.com`` is a
different entity (SQL data platform blog) and stays out of scope.
"""

from __future__ import annotations

import unittest
from datetime import date

from investment_monitor.models import MARKET_US, CollectionRequest
from investment_monitor.registry import create_default_registry
from investment_monitor.sources.yellowbrick import YellowbrickConnector


class YellowbrickStubTests(unittest.TestCase):
    def test_connector_attributes(self) -> None:
        connector = YellowbrickConnector()
        self.assertEqual(connector.name, "yellowbrick")
        self.assertEqual(connector.provider, "Yellowbrick Investing")
        self.assertEqual(connector.status, "stub")

    def test_collect_is_empty_stub(self) -> None:
        connector = YellowbrickConnector()
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
        self.assertIn("joinyellowbrick.com", message)
        self.assertIn("404", message)
        self.assertIn("waitlist", message)

    def test_collect_records_each_us_ticker(self) -> None:
        connector = YellowbrickConnector()
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
        connector = YellowbrickConnector()
        request = CollectionRequest(
            tickers=("0700",),
            start_date=date(2026, 8, 11),
            end_date=date(2026, 8, 11),
            markets={"0700": "hk"},
        )
        items = connector.collect(request)
        self.assertEqual(items, [])
        self.assertEqual(connector.last_errors, ())

    def test_registry_registers_yellowbrick(self) -> None:
        registry = create_default_registry()
        self.assertIsNotNone(registry.factory_for("yellowbrick"))
        connector = registry.factory_for("yellowbrick")()
        self.assertEqual(connector.name, "yellowbrick")
        self.assertEqual(connector.status, "stub")

    def test_collect_mixed_us_and_other(self) -> None:
        # Only US tickers get honest stub notes; other markets are skipped
        # without a network attempt or failure record.
        connector = YellowbrickConnector()
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
