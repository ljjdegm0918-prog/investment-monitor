from datetime import date, datetime, timezone
import json
from pathlib import Path
import unittest

from investment_monitor import (
    CollectionRequest,
    EqsNlClient,
    EqsNlConnector,
    EqsNlRequestError,
)
from investment_monitor.registry import create_default_registry
from provenance_assertions import assert_official_provenance


FIXTURES = Path(__file__).parent / "fixtures" / "eqs_nl"


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
    return EqsNlClient(opener=opener, requests_per_second=1000)


class EqsNlClientTests(unittest.TestCase):
    def test_parses_records_and_filters_amsterdam_window(self) -> None:
        body = (FIXTURES / "eqs_airbus.json").read_bytes()
        opener = FakeOpener(body)
        client = make_client(opener)

        records = client.fetch_by_isin(
            "NL0000235190",
            date(2026, 8, 1),
            date(2026, 8, 6),
        )

        self.assertEqual(len(records), 1)
        self.assertIn("isin=NL0000235190", opener.requested[0])
        first = records[0]
        self.assertEqual(first["external_id"], "73f3a9ba-6003-4506-900b-50bc834927d6")
        self.assertEqual(first["title"], "Airbus reports Half-Year (H1) 2026 results")
        self.assertEqual(
            first["published_at"],
            datetime(2026, 8, 5, 7, 30, tzinfo=timezone.utc),
        )
        self.assertEqual(first["isin"], "NL0000235190")
        self.assertTrue(first["url"].startswith("https://www.eqs-news.com/news/"))

    def test_malformed_json_raises_data_error(self) -> None:
        from investment_monitor import EqsNlDataError

        client = make_client(FakeOpener(b"<html>blocked</html>"))

        with self.assertRaises(EqsNlDataError):
            client.fetch_by_isin(
                "NL0000235190",
                date(2026, 8, 1),
                date(2026, 8, 6),
            )


class EqsNlConnectorTests(unittest.TestCase):
    def request(self, tickers, markets):
        return CollectionRequest(
            tickers=tickers,
            start_date=date(2026, 8, 1),
            end_date=date(2026, 8, 6),
            markets=markets,
        )

    def make_connector(self, universe=None):
        opener = FakeOpener((FIXTURES / "eqs_airbus.json").read_bytes())
        connector = EqsNlConnector(
            client=make_client(opener),
            universe=universe,
        )
        return connector, opener

    def test_non_nl_markets_are_skipped_with_zero_http(self) -> None:
        connector, opener = self.make_connector()

        items = connector.collect(
            self.request(("AAPL", "VOD"), {"AAPL": "us", "VOD": "uk"})
        )

        self.assertEqual(items, [])
        self.assertEqual(connector.last_errors, ())
        self.assertEqual(opener.requested, [])

    def test_nl_without_universe_isin_is_skipped_honestly(self) -> None:
        connector, opener = self.make_connector(universe={})

        items = connector.collect(
            self.request(("ASML",), {"ASML": "nl"})
        )

        self.assertEqual(items, [])
        self.assertEqual(opener.requested, [])
        self.assertEqual(connector.last_errors, (("ASML", "no_universe_isin"),))

    def test_nl_typed_isin_collects_records(self) -> None:
        connector, opener = self.make_connector()

        items = connector.collect(
            self.request(("NL0000235190",), {"NL0000235190": "nl"})
        )

        self.assertEqual(len(items), 1)
        first = items[0]
        self.assertEqual(first.source, "eqs_nl")
        self.assertEqual(first.source_type, "regulatory_filing")
        self.assertEqual(first.tickers, ("NL0000235190",))
        self.assertEqual(first.market, "nl")
        self.assertEqual(first.document_type, "adhoc")
        self.assertEqual(
            first.raw_metadata["provider"], "eqs_news"
        )
        self.assertEqual(first.raw_metadata["isin"], "NL0000235190")
        self.assertIn("isin=NL0000235190", opener.requested[0])
        payload = json.loads(
            (FIXTURES / "eqs_airbus.json").read_text(encoding="utf-8")
        )["records"][0]
        assert_official_provenance(
            self,
            first,
            expected_payload=payload,
            official_source_id=payload["id"],
            official_source_url=first.url,
            retrieval_url=opener.requested[0],
            raw_payload_format="json",
            classification_code=payload["categoryCode"],
            classification_label=payload["category"],
            published_at_raw=payload["dateUtc"],
            published_timezone="UTC",
        )

    def test_nl_universe_isin_matches_ticker(self) -> None:
        connector, _ = self.make_connector(
            universe={
                "AIR": {
                    "name": "Airbus SE",
                    "exchange": "Euronext Amsterdam",
                    "isin": "NL0000235190",
                }
            }
        )

        items = connector.collect(
            self.request(("AIR",), {"AIR": "nl"})
        )

        self.assertEqual(len(items), 1)
        self.assertEqual(items[0].tickers, ("AIR",))

    def test_single_ticker_failure_raises_and_records_error(self) -> None:
        def failing_opener(request, timeout=None):
            raise EqsNlRequestError("eqs blocked")

        connector = EqsNlConnector(
            client=make_client(failing_opener),
            universe={"ASML": {"name": "ASML", "isin": "NL0010273215"}},
        )

        with self.assertRaises(EqsNlRequestError):
            connector.collect(self.request(("ASML",), {"ASML": "nl"}))

        self.assertEqual(len(connector.last_errors), 1)
        self.assertEqual(connector.last_errors[0][0], "ASML")

    def test_registry_registers_eqs_nl_without_secret_field(self) -> None:
        registry = create_default_registry()

        self.assertIsNotNone(registry.factory_for("eqs_nl"))
        self.assertEqual(registry.secret_fields_for("eqs_nl"), ())


if __name__ == "__main__":
    unittest.main()
