from datetime import date, datetime, timezone
from pathlib import Path
import unittest

from investment_monitor import (
    CollectionRequest,
    EqsItClient,
    EqsItConnector,
    EqsItRequestError,
)
from investment_monitor.registry import create_default_registry


FIXTURES = Path(__file__).parent / "fixtures" / "eqs_it"


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
    return EqsItClient(opener=opener, requests_per_second=1000)


class EqsItClientTests(unittest.TestCase):
    def test_parses_records_and_filters_rome_window(self) -> None:
        body = (FIXTURES / "eqs_unicredit.json").read_bytes()
        opener = FakeOpener(body)
        client = make_client(opener)

        records = client.fetch_by_isin(
            "IT0005239360",
            date(2026, 8, 1),
            date(2026, 8, 6),
        )

        self.assertEqual(len(records), 1)
        self.assertIn("isin=IT0005239360", opener.requested[0])
        first = records[0]
        self.assertEqual(first["external_id"], "211252eb-8c10-4827-ac18-e9a7c4b8dd43")
        self.assertEqual(first["title"], "UniCredit launches public tender offer")
        self.assertEqual(
            first["published_at"],
            datetime(2026, 8, 5, 7, 30, tzinfo=timezone.utc),
        )
        self.assertEqual(first["isin"], "IT0005239360")

    def test_malformed_json_raises_data_error(self) -> None:
        from investment_monitor import EqsItDataError

        client = make_client(FakeOpener(b"<html>blocked</html>"))

        with self.assertRaises(EqsItDataError):
            client.fetch_by_isin(
                "IT0005239360",
                date(2026, 8, 1),
                date(2026, 8, 6),
            )


class EqsItConnectorTests(unittest.TestCase):
    def request(self, tickers, markets):
        return CollectionRequest(
            tickers=tickers,
            start_date=date(2026, 8, 1),
            end_date=date(2026, 8, 6),
            markets=markets,
        )

    def make_connector(self, universe=None):
        opener = FakeOpener((FIXTURES / "eqs_unicredit.json").read_bytes())
        connector = EqsItConnector(
            client=make_client(opener),
            universe=universe,
        )
        return connector, opener

    def test_non_it_markets_are_skipped_with_zero_http(self) -> None:
        connector, opener = self.make_connector()

        items = connector.collect(
            self.request(("AAPL", "VOD"), {"AAPL": "us", "VOD": "uk"})
        )

        self.assertEqual(items, [])
        self.assertEqual(connector.last_errors, ())
        self.assertEqual(opener.requested, [])

    def test_it_without_universe_isin_is_skipped_honestly(self) -> None:
        connector, opener = self.make_connector(universe={})

        items = connector.collect(
            self.request(("ENI",), {"ENI": "it"})
        )

        self.assertEqual(items, [])
        self.assertEqual(opener.requested, [])
        self.assertEqual(connector.last_errors, (("ENI", "no_universe_isin"),))

    def test_it_typed_isin_collects_records(self) -> None:
        connector, opener = self.make_connector()

        items = connector.collect(
            self.request(("IT0005239360",), {"IT0005239360": "it"})
        )

        self.assertEqual(len(items), 1)
        first = items[0]
        self.assertEqual(first.source, "eqs_it")
        self.assertEqual(first.source_type, "regulatory_filing")
        self.assertEqual(first.tickers, ("IT0005239360",))
        self.assertEqual(first.market, "it")
        self.assertEqual(first.document_type, "wpug")
        self.assertEqual(first.raw_metadata["provider"], "eqs_news")
        self.assertEqual(first.raw_metadata["isin"], "IT0005239360")
        self.assertIn("isin=IT0005239360", opener.requested[0])

    def test_it_universe_isin_matches_ticker(self) -> None:
        connector, _ = self.make_connector(
            universe={
                "UCG": {
                    "name": "UniCredit S.p.A.",
                    "exchange": "Euronext Milan",
                    "isin": "IT0005239360",
                }
            }
        )

        items = connector.collect(
            self.request(("UCG",), {"UCG": "it"})
        )

        self.assertEqual(len(items), 1)
        self.assertEqual(items[0].tickers, ("UCG",))

    def test_single_ticker_failure_raises_and_records_error(self) -> None:
        def failing_opener(request, timeout=None):
            raise EqsItRequestError("eqs blocked")

        connector = EqsItConnector(
            client=make_client(failing_opener),
            universe={"ENI": {"name": "ENI", "isin": "IT0003132476"}},
        )

        with self.assertRaises(EqsItRequestError):
            connector.collect(self.request(("ENI",), {"ENI": "it"}))

        self.assertEqual(len(connector.last_errors), 1)
        self.assertEqual(connector.last_errors[0][0], "ENI")

    def test_registry_registers_eqs_it_without_secret_field(self) -> None:
        registry = create_default_registry()

        self.assertIsNotNone(registry.factory_for("eqs_it"))
        self.assertEqual(registry.secret_fields_for("eqs_it"), ())


if __name__ == "__main__":
    unittest.main()
