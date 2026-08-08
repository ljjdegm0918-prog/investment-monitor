from datetime import date, datetime, timezone
import os
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from investment_monitor import (
    CollectionRequest,
    YahooCaNewsConnector,
    YahooCaNewsDataError,
    YahooCaNewsRequestError,
)
from investment_monitor.registry import create_default_registry


FIXTURES = Path(__file__).parent / "fixtures" / "ca_news"


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
        url = request.full_url
        self.requested.append(url)
        return FakeResponse(self.body)


class YahooCaClientTests(unittest.TestCase):
    def test_parses_rss_and_filters_dates(self) -> None:
        from investment_monitor.sources.ca_news.yahoo.client import (
            YahooCaNewsClient,
            _parse_rss,
        )

        body = (FIXTURES / "yahoo_ca_ry.xml").read_bytes()
        records = _parse_rss(
            body,
            start_date=date(2026, 8, 1),
            end_date=date(2026, 8, 6),
        )

        self.assertEqual(len(records), 2)
        first = records[0]
        self.assertEqual(first["external_id"], "110000101")
        self.assertEqual(first["title"], "Royal Bank of Canada raises dividend")
        self.assertEqual(
            first["url"],
            "https://ca.finance.yahoo.com/news/royal-bank-dividend-110000101.html",
        )
        self.assertEqual(
            first["published"],
            datetime(2026, 8, 5, 13, 30, tzinfo=timezone.utc),
        )
        self.assertEqual(
            first["summary"],
            "Royal Bank of Canada announced a dividend increase.",
        )

        opener = FakeOpener(body)
        client = YahooCaNewsClient(
            opener=opener,
            requests_per_second=1000,
        )
        fetched = client.fetch_news(
            "RY.TO",
            date(2026, 8, 1),
            date(2026, 8, 6),
        )
        self.assertEqual(len(fetched), 2)
        self.assertIn("s=RY.TO", opener.requested[0])
        self.assertIn("region=CA", opener.requested[0])
        self.assertIn("lang=en-CA", opener.requested[0])

    def test_empty_channel_returns_empty_list(self) -> None:
        from investment_monitor.sources.ca_news.yahoo.client import _parse_rss

        body = b'<?xml version="1.0"?><rss version="2.0"><channel><title>x</title></channel></rss>'
        records = _parse_rss(
            body,
            start_date=date(2026, 8, 1),
            end_date=date(2026, 8, 6),
        )

        self.assertEqual(records, [])

    def test_malformed_feed_raises_data_error(self) -> None:
        from investment_monitor.sources.ca_news.yahoo.client import _parse_rss

        with self.assertRaises(YahooCaNewsDataError):
            _parse_rss(
                b"<html><body>blocked</body></html>",
                start_date=date(2026, 8, 1),
                end_date=date(2026, 8, 6),
            )


class YahooCaSymbolTests(unittest.TestCase):
    def test_default_symbol_rules_from_universe_board(self) -> None:
        from investment_monitor.sources.ca_news.yahoo.connector import (
            _default_symbol_for,
        )

        with TemporaryDirectory() as temporary_directory:
            cache_path = Path(temporary_directory) / "ca_universe.json"
            cache_path.write_text(
                (
                    '{"updated_at":"2026-08-08T00:00:00+00:00",'
                    '"items":['
                    '{"ticker":"RY","name":"Royal Bank of Canada",'
                    '"board":"TSX","exchange":"TSX"},'
                    '{"ticker":"AUMB","name":"1911 Gold Corporation",'
                    '"board":"TSXV","exchange":"TSXV"}]}'
                ),
                encoding="utf-8",
            )
            with patch.dict(
                os.environ,
                {"CA_UNIVERSE_CACHE_PATH": str(cache_path)},
                clear=False,
            ):
                self.assertEqual(_default_symbol_for("RY"), "RY.TO")
                self.assertEqual(_default_symbol_for("SHOP"), "SHOP.TO")
                self.assertEqual(_default_symbol_for("AUMB"), "AUMB.V")


class YahooCaConnectorTests(unittest.TestCase):
    def request(self, tickers, markets):
        return CollectionRequest(
            tickers=tickers,
            start_date=date(2026, 8, 1),
            end_date=date(2026, 8, 6),
            markets=markets,
        )

    def make_connector(self, symbol_for=None):
        from investment_monitor.sources.ca_news.yahoo.client import (
            YahooCaNewsClient,
        )

        opener = FakeOpener((FIXTURES / "yahoo_ca_ry.xml").read_bytes())
        connector = YahooCaNewsConnector(
            client=YahooCaNewsClient(
                opener=opener,
                requests_per_second=1000,
            ),
            symbol_for=symbol_for,
        )
        return connector, opener

    def test_non_ca_markets_are_skipped_with_zero_http(self) -> None:
        connector, opener = self.make_connector()

        items = connector.collect(
            self.request(("AAPL", "VOD"), {"AAPL": "us", "VOD": "uk"})
        )

        self.assertEqual(items, [])
        self.assertEqual(connector.last_errors, ())
        self.assertEqual(opener.requested, [])

    def test_ca_maps_news_with_canonical_ticker(self) -> None:
        connector, opener = self.make_connector()

        items = connector.collect(
            self.request(("RY.TO",), {"RY.TO": "ca"})
        )

        by_id = {item.external_id: item for item in items}
        self.assertIn("110000101", by_id)
        first = by_id["110000101"]
        self.assertEqual(first.source, "yahoo_ca")
        self.assertEqual(first.source_type, "news")
        self.assertEqual(first.tickers, ("RY",))
        self.assertEqual(first.market, "ca")
        self.assertEqual(first.document_type, "news")
        self.assertEqual(first.raw_metadata["provider"], "yahoo_finance_rss")
        self.assertEqual(first.raw_metadata["langs"], "en")
        self.assertIn("s=RY.TO", opener.requested[0])

    def test_symbol_for_injection_is_used(self) -> None:
        connector, opener = self.make_connector(
            symbol_for=lambda code: f"{code}.TEST"
        )

        connector.collect(self.request(("RY",), {"RY": "ca"}))

        self.assertIn("s=RY.TEST", opener.requested[0])

    def test_date_window_filters_old_items(self) -> None:
        connector, _ = self.make_connector()

        items = connector.collect(
            self.request(("RY",), {"RY": "ca"})
        )

        self.assertEqual(len(items), 2)

    def test_single_ticker_failure_raises_and_records_error(self) -> None:
        from investment_monitor.sources.ca_news.yahoo.client import (
            YahooCaNewsClient,
        )

        def failing_opener(request, timeout=None):
            raise YahooCaNewsRequestError("yahoo blocked")

        connector = YahooCaNewsConnector(
            client=YahooCaNewsClient(
                opener=failing_opener,
                requests_per_second=1000,
            )
        )

        with self.assertRaises(YahooCaNewsRequestError):
            connector.collect(self.request(("RY",), {"RY": "ca"}))

        self.assertEqual(len(connector.last_errors), 1)
        self.assertEqual(connector.last_errors[0][0], "RY")

    def test_registry_registers_yahoo_ca_without_secret_field(self) -> None:
        registry = create_default_registry()

        self.assertIsNotNone(registry.factory_for("yahoo_ca"))
        self.assertEqual(registry.secret_fields_for("yahoo_ca"), ())


if __name__ == "__main__":
    unittest.main()
