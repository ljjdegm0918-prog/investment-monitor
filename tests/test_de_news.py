"""Tests for Yahoo DE / Google News DE connectors."""

from datetime import date
from pathlib import Path
import unittest

from investment_monitor.models import CollectionRequest
from investment_monitor.sources.de_news.google.client import GoogleDeNewsClient
from investment_monitor.sources.de_news.google.connector import GoogleDeNewsConnector
from investment_monitor.sources.de_news.yahoo.client import YahooDeNewsClient
from investment_monitor.sources.de_news.yahoo.connector import YahooDeNewsConnector

FIXTURES = Path(__file__).parent / "fixtures" / "de_news"


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
    def __init__(self, mapping: dict) -> None:
        self.mapping = mapping
        self.requested: list = []

    def __call__(self, request, timeout=None):
        self.requested.append(request.full_url)
        for key, body in self.mapping.items():
            if key in request.full_url:
                return FakeResponse(body)
        raise AssertionError(f"unexpected url: {request.full_url}")


class DeNewsTests(unittest.TestCase):
    def test_yahoo_de_merges_de_and_en(self) -> None:
        opener = FakeOpener(
            {
                "lang=de-DE": (FIXTURES / "yahoo_de_sap.xml").read_bytes(),
                "lang=en-US": (FIXTURES / "yahoo_de_sap_en.xml").read_bytes(),
            }
        )
        connector = YahooDeNewsConnector(
            client=YahooDeNewsClient(opener=opener, requests_per_second=1000)
        )
        items = connector.collect(
            CollectionRequest(
                tickers=("SAP",),
                start_date=date(2026, 8, 1),
                end_date=date(2026, 8, 9),
                markets={"SAP": "de"},
            )
        )
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0].source, "yahoo_de")
        self.assertEqual(items[0].market, "de")
        self.assertEqual(items[0].tickers, ("SAP",))
        self.assertIn("SAP.DE", opener.requested[0])
        self.assertEqual(items[0].raw_metadata.get("langs"), "en+de")

    def test_google_de_parses_fixture(self) -> None:
        opener = FakeOpener(
            {"news.google.com": (FIXTURES / "google_de_sap.xml").read_bytes()}
        )
        connector = GoogleDeNewsConnector(
            client=GoogleDeNewsClient(opener=opener, requests_per_second=1000)
        )
        items = connector.collect(
            CollectionRequest(
                tickers=("SAP",),
                start_date=date(2026, 8, 1),
                end_date=date(2026, 8, 9),
                markets={"SAP": "de"},
            )
        )
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0].source, "google_news_de")
        self.assertIn("hl=de", opener.requested[0])
        self.assertIn("ceid=DE:de", opener.requested[0])

    def test_non_de_skips_without_http(self) -> None:
        opener = FakeOpener({})
        request = CollectionRequest(
            tickers=("AAPL",),
            start_date=date(2026, 8, 1),
            end_date=date(2026, 8, 9),
            markets={"AAPL": "us"},
        )
        self.assertEqual(
            YahooDeNewsConnector(
                client=YahooDeNewsClient(opener=opener, requests_per_second=1000)
            ).collect(request),
            [],
        )
        self.assertEqual(
            GoogleDeNewsConnector(
                client=GoogleDeNewsClient(opener=opener, requests_per_second=1000)
            ).collect(request),
            [],
        )
        self.assertEqual(opener.requested, [])


if __name__ == "__main__":
    unittest.main()
