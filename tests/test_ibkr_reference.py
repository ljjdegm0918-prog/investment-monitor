"""IBKR reference adapter tests (P1-6, mock without gateway session)."""

import unittest

from investment_monitor.universe.ibkr_reference import (
    IbkrReferenceError,
    enrich_with_ibkr_conids,
    ibkr_conid_for,
)


class FakeSession:
    def __init__(self, mapping=None):
        self.mapping = mapping or {}

    def lookup_contract(self, symbol, market):
        return self.mapping.get((symbol, market))


class IbkrReferenceTests(unittest.TestCase):
    def test_mock_without_session_never_invents_conid(self):
        self.assertIsNone(ibkr_conid_for("SAP", "de"))
        rows = enrich_with_ibkr_conids([{"symbol": "SAP", "market": "de"}])
        self.assertEqual(rows[0], {"symbol": "SAP", "market": "de"})

    def test_session_lookup_returns_conid(self):
        session = FakeSession({("SAP", "de"): {"conid": 123456}})
        self.assertEqual(ibkr_conid_for("SAP", "de", session), "123456")
        rows = enrich_with_ibkr_conids(
            [{"symbol": "SAP", "market": "de"}], session
        )
        self.assertEqual(rows[0]["ibkr_conid"], "123456")

    def test_bad_session_object_raises(self):
        with self.assertRaises(IbkrReferenceError):
            ibkr_conid_for("SAP", "de", session=object())


if __name__ == "__main__":
    unittest.main()
