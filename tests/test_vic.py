"""Unit tests for the Value Investors Club connector — honest stub.

Mirrors the ``x_community`` / ``yellowbrick`` registered-stub tests: the spike
(2026-08-11, see ``tests/fixtures/vic/probe_public.py``) showed VIC has no
stable public login-free ticker+day surface — ``/feed``/``/rss``/``/api/ideas``
are HTML shells, ``/ideas?symbol=TICKER`` does not filter, and guest access is
membership signup with 45-day delayed ideas only. So ``collect()`` never hits
the network and returns ``[]`` with honest ``last_errors``. No live network is
used in these tests.
"""

from __future__ import annotations

import unittest
from datetime import date

from investment_monitor.models import CollectionRequest
from investment_monitor.registry import create_default_registry
from investment_monitor.sources.vic import VicConnector


class VicStubTests(unittest.TestCase):
    def test_connector_attributes(self) -> None:
        connector = VicConnector()
        self.assertEqual(connector.name, "vic")
        self.assertEqual(connector.provider, "Value Investors Club")
        self.assertEqual(connector.status, "stub")

    def test_collect_is_empty_stub(self) -> None:
        connector = VicConnector()
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
        self.assertIn("valueinvestorsclub.com", message)
        self.assertIn("45-day", message)
        self.assertIn("does not filter", message)

    def test_collect_records_each_us_ticker(self) -> None:
        connector = VicConnector()
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
        connector = VicConnector()
        request = CollectionRequest(
            tickers=("0700",),
            start_date=date(2026, 8, 11),
            end_date=date(2026, 8, 11),
            markets={"0700": "hk"},
        )
        items = connector.collect(request)
        self.assertEqual(items, [])
        self.assertEqual(connector.last_errors, ())

    def test_registry_registers_vic(self) -> None:
        registry = create_default_registry()
        self.assertIsNotNone(registry.factory_for("vic"))
        connector = registry.factory_for("vic")()
        self.assertEqual(connector.name, "vic")
        self.assertEqual(connector.status, "stub")

    def test_collect_mixed_us_and_other(self) -> None:
        connector = VicConnector()
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
