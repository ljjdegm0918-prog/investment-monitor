"""Tests for EQS News / DGAP disclosures (market=de)."""

from datetime import date
from pathlib import Path
import unittest

from investment_monitor.models import CollectionRequest
from investment_monitor.sources.eqs_dgap import EqsDgapClient, EqsDgapConnector

FIXTURES = Path(__file__).parent / "fixtures" / "eqs_dgap"
SAP_UNIVERSE = {
    "SAP": {"name": "SAP SE O.N.", "isin": "DE0007164600", "board": "DAX", "exchange": "DAX"},
}


class FakeResponse:
    def __init__(self, body: bytes) -> None:
        self._body = body

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return None

    def read(self) -> bytes:
        return self._body


class FakeOpener:
    def __init__(self, body: bytes) -> None:
        self.body = body
        self.requested: list = []

    def __call__(self, request, timeout=None):
        self.requested.append(request.full_url)
        return FakeResponse(self.body)


class EqsDgapTests(unittest.TestCase):
    def test_fixture_parses_and_filters_berlin_window(self) -> None:
        opener = FakeOpener((FIXTURES / "news_sap.json").read_bytes())
        connector = EqsDgapConnector(
            client=EqsDgapClient(opener=opener, requests_per_second=1000),
            universe=SAP_UNIVERSE,
        )
        items = connector.collect(
            CollectionRequest(
                tickers=("SAP",),
                start_date=date(2026, 8, 1),
                end_date=date(2026, 8, 8),
                markets={"SAP": "de"},
            )
        )
        self.assertEqual(len(items), 2)
        ids = {item.external_id for item in items}
        self.assertEqual(
            ids,
            {
                "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
                "11111111-2222-3333-4444-555555555555",
            },
        )
        self.assertTrue(all(item.source == "eqs_dgap" for item in items))
        self.assertTrue(all(item.market == "de" for item in items))
        self.assertTrue(all(item.source_type == "regulatory_filing" for item in items))
        self.assertIn("isin=DE0007164600", opener.requested[0])

    def test_skips_non_de_without_http(self) -> None:
        opener = FakeOpener(b"{}")
        connector = EqsDgapConnector(
            client=EqsDgapClient(opener=opener, requests_per_second=1000),
            universe=SAP_UNIVERSE,
        )
        items = connector.collect(
            CollectionRequest(
                tickers=("SAP",),
                start_date=date(2026, 8, 1),
                end_date=date(2026, 8, 8),
                markets={"SAP": "us"},
            )
        )
        self.assertEqual(items, [])
        self.assertEqual(opener.requested, [])

    def test_missing_isin_is_honest_empty(self) -> None:
        opener = FakeOpener(b"{}")
        connector = EqsDgapConnector(
            client=EqsDgapClient(opener=opener, requests_per_second=1000),
            universe={},
        )
        items = connector.collect(
            CollectionRequest(
                tickers=("SAP",),
                start_date=date(2026, 8, 1),
                end_date=date(2026, 8, 8),
                markets={"SAP": "de"},
            )
        )
        self.assertEqual(items, [])
        self.assertEqual(connector.last_errors, (("SAP", "no_universe_isin"),))
        self.assertEqual(opener.requested, [])


if __name__ == "__main__":
    unittest.main()
