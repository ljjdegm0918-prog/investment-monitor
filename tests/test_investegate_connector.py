from datetime import date, datetime, timezone
from pathlib import Path
import unittest

from investment_monitor import (
    CollectionRequest,
    InvestegateConnector,
    InvestegateRequestError,
)


FIXTURES = Path(__file__).parent / "fixtures" / "investegate"


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


class InvestegateConnectorTests(unittest.TestCase):
    def request(self, tickers, markets):
        return CollectionRequest(
            tickers=tickers,
            start_date=date(2026, 8, 1),
            end_date=date(2026, 8, 5),
            markets=markets,
        )

    def test_non_uk_markets_are_skipped_with_zero_http(self) -> None:
        from investment_monitor.sources.investegate.client import (
            InvestegateClient,
        )

        opener = FakeOpener((FIXTURES / "announcements.html").read_bytes())
        connector = InvestegateConnector(
            client=InvestegateClient(opener=opener, requests_per_second=1000)
        )
        items = connector.collect(
            self.request(("AAPL", "VOD"), {"AAPL": "us", "VOD": "hk"})
        )

        self.assertEqual(items, [])
        self.assertEqual(connector.last_errors, ())
        self.assertEqual(opener.requested, [])

    def test_uk_maps_announcements_and_normalizes_ticker(self) -> None:
        from investment_monitor.sources.investegate.client import (
            InvestegateClient,
        )

        opener = FakeOpener((FIXTURES / "announcements.html").read_bytes())
        connector = InvestegateConnector(
            client=InvestegateClient(opener=opener, requests_per_second=1000)
        )

        items = connector.collect(
            self.request(("vod",), {"vod": "uk"})
        )

        self.assertEqual(len(items), 2)
        first = items[0]
        self.assertEqual(first.source, "investegate")
        self.assertEqual(first.source_type, "regulatory_filing")
        self.assertEqual(first.external_id, "9707019")
        self.assertEqual(first.tickers, ("VOD",))
        self.assertEqual(first.market, "uk")
        self.assertEqual(first.title, "Director/PDMR Shareholding")
        self.assertEqual(first.document_type, "rns_announcement")
        self.assertEqual(
            first.published_at,
            datetime(2026, 8, 5, 15, 18, tzinfo=timezone.utc),
        )
        self.assertIn("/announcement/rns/", first.url)
        self.assertEqual(first.raw_metadata["rns_id"], "9707019")
        self.assertEqual(first.raw_metadata["source_label"], "RNS")
        self.assertIn("/company/VOD", opener.requested[0])

    def test_failure_is_recorded(self) -> None:
        from investment_monitor.sources.investegate.client import (
            InvestegateClient,
        )

        def failing_opener(request, timeout=None):
            raise InvestegateRequestError("investegate blocked")

        connector = InvestegateConnector(
            client=InvestegateClient(
                opener=failing_opener,
                requests_per_second=1000,
            )
        )

        with self.assertRaises(InvestegateRequestError):
            connector.collect(
                self.request(("VOD",), {"VOD": "uk"})
            )

        self.assertEqual(len(connector.last_errors), 1)
        self.assertEqual(connector.last_errors[0][0], "VOD")


if __name__ == "__main__":
    unittest.main()
