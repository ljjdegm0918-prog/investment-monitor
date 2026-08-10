from datetime import date, datetime, timezone
from pathlib import Path
import unittest

from investment_monitor import (
    CollectionRequest,
    EqsChClient,
    EqsChConnector,
    EqsChDataError,
    EqsChRequestError,
)
from investment_monitor.registry import create_default_registry


FIXTURES = Path(__file__).parent / "fixtures" / "eqs_ch"


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


def make_client(opener):
    return EqsChClient(opener=opener, requests_per_second=1000)


class EqsChClientTests(unittest.TestCase):
    def test_parses_records_and_filters_zurich_window(self) -> None:
        body = (FIXTURES / "eqs_roche.json").read_bytes()
        opener = FakeOpener(body)
        client = make_client(opener)

        records = client.fetch_by_isin(
            "CH0012032113",
            date(2026, 8, 1),
            date(2026, 8, 6),
        )

        self.assertEqual(len(records), 2)
        self.assertIn("isin=CH0012032113", opener.requested[0])
        first = records[0]
        self.assertEqual(
            first["external_id"],
            "c2b53744-7d61-45a4-9c5f-131d035c9a4c",
        )
        self.assertEqual(
            first["title"],
            "Roche announces new data at medical congress",
        )
        self.assertEqual(
            first["published_at"],
            datetime(2026, 8, 5, 7, 30, tzinfo=timezone.utc),
        )
        self.assertEqual(first["isin"], "CH0012032113")

    def test_malformed_json_raises_data_error(self) -> None:
        client = make_client(FakeOpener(b"<html>blocked</html>"))

        with self.assertRaises(EqsChDataError):
            client.fetch_by_isin(
                "CH0012032113",
                date(2026, 8, 1),
                date(2026, 8, 6),
            )


class EqsChConnectorTests(unittest.TestCase):
    def request(self, tickers, markets):
        return CollectionRequest(
            tickers=tickers,
            start_date=date(2026, 8, 1),
            end_date=date(2026, 8, 6),
            markets=markets,
        )

    def make_connector(self, universe=None):
        opener = FakeOpener((FIXTURES / "eqs_roche.json").read_bytes())
        connector = EqsChConnector(
            client=make_client(opener),
            universe=universe,
        )
        return connector, opener

    def test_non_ch_markets_are_skipped_with_zero_http(self) -> None:
        connector, opener = self.make_connector()

        items = connector.collect(
            self.request(("AAPL", "VOD"), {"AAPL": "us", "VOD": "uk"})
        )

        self.assertEqual(items, [])
        self.assertEqual(connector.last_errors, ())
        self.assertEqual(opener.requested, [])

    def test_ch_without_universe_isin_is_skipped_honestly(self) -> None:
        connector, opener = self.make_connector(universe={})

        items = connector.collect(
            self.request(("NESN",), {"NESN": "ch"})
        )

        self.assertEqual(items, [])
        self.assertEqual(opener.requested, [])
        self.assertEqual(connector.last_errors, (("NESN", "no_universe_isin"),))

    def test_ch_typed_isin_collects_records(self) -> None:
        connector, opener = self.make_connector()

        items = connector.collect(
            self.request(("CH0012032113",), {"CH0012032113": "ch"})
        )

        self.assertEqual(len(items), 2)
        first = items[0]
        self.assertEqual(first.source, "eqs_ch")
        self.assertEqual(first.source_type, "regulatory_filing")
        self.assertEqual(first.tickers, ("CH0012032113",))
        self.assertEqual(first.market, "ch")
        self.assertEqual(first.document_type, "corporate")
        self.assertEqual(first.raw_metadata["provider"], "eqs_news")
        self.assertEqual(first.raw_metadata["isin"], "CH0012032113")
        self.assertIn("isin=CH0012032113", opener.requested[0])

    def test_ch_universe_isin_matches_ticker(self) -> None:
        connector, _ = self.make_connector(
            universe={
                "ROG": {
                    "name": "Roche Holding AG",
                    "exchange": "SIX Main Standard",
                    "isin": "CH0012032113",
                }
            }
        )

        items = connector.collect(
            self.request(("ROG",), {"ROG": "ch"})
        )

        self.assertEqual(len(items), 2)
        self.assertEqual(items[0].tickers, ("ROG",))

    def test_single_ticker_failure_raises_and_records_error(self) -> None:
        def failing_opener(request, timeout=None):
            raise EqsChRequestError("eqs blocked")

        connector = EqsChConnector(
            client=make_client(failing_opener),
            universe={"NESN": {"name": "Nestle", "isin": "CH0038863350"}},
        )

        with self.assertRaises(EqsChRequestError):
            connector.collect(self.request(("NESN",), {"NESN": "ch"}))

        self.assertEqual(len(connector.last_errors), 1)
        self.assertEqual(connector.last_errors[0][0], "NESN")

    def test_registry_registers_eqs_ch_without_secret_field(self) -> None:
        registry = create_default_registry()

        self.assertIsNotNone(registry.factory_for("eqs_ch"))
        self.assertEqual(registry.secret_fields_for("eqs_ch"), ())


if __name__ == "__main__":
    unittest.main()
