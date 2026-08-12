from datetime import date, datetime, timezone
from pathlib import Path
import unittest

from investment_monitor import (
    CollectionRequest,
    YahooAqNewsConnector,
    YahooAqNewsDataError,
    YahooAqNewsRequestError,
)
from investment_monitor.registry import create_default_registry


FIXTURES = Path(__file__).parent / "fixtures" / "aq_news"


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
    def __init__(self, gb: bytes, us: bytes) -> None:
        self.gb = gb
        self.us = us
        self.requested: list = []

    def __call__(self, request, timeout=None):
        url = request.full_url
        self.requested.append(url)
        body = self.gb if "lang=en-GB" in url else self.us
        return FakeResponse(body)


class YahooAqClientTests(unittest.TestCase):
    def test_parses_rss_and_filters_dates(self) -> None:
        from investment_monitor.sources.aq_news.yahoo.client import (
            YahooAqNewsClient,
            _parse_rss,
        )

        body = (FIXTURES / "yahoo_aq_adb.xml").read_bytes()
        records = _parse_rss(
            body,
            start_date=date(2026, 8, 1),
            end_date=date(2026, 8, 8),
        )

        self.assertEqual(len(records), 2)
        first = records[0]
        self.assertEqual(first["external_id"], "110000601")
        self.assertEqual(
            first["title"],
            "Adnams plc raises funds for new brewery",
        )
        self.assertEqual(
            first["published"],
            datetime(2026, 8, 5, 8, 30, tzinfo=timezone.utc),
        )

        opener = FakeOpener(body, b"")
        client = YahooAqNewsClient(
            opener=opener,
            requests_per_second=1000,
        )
        fetched = client.fetch_news(
            "ADB.AQ",
            date(2026, 8, 1),
            date(2026, 8, 8),
        )
        self.assertEqual(len(fetched), 2)
        self.assertIn("s=ADB.AQ", opener.requested[0])
        self.assertIn("region=GB", opener.requested[0])
        self.assertIn("lang=en-GB", opener.requested[0])

    def test_malformed_feed_raises_data_error(self) -> None:
        from investment_monitor.sources.aq_news.yahoo.client import _parse_rss

        with self.assertRaises(YahooAqNewsDataError):
            _parse_rss(
                b"<html><body>blocked</body></html>",
                start_date=date(2026, 8, 1),
                end_date=date(2026, 8, 8),
            )


class YahooAqSymbolTests(unittest.TestCase):
    def test_symbol_appends_aq_suffix(self) -> None:
        from investment_monitor.sources.aq_news.symbols import aq_yahoo_symbol

        self.assertEqual(aq_yahoo_symbol("ADB"), "ADB.AQ")
        self.assertEqual(aq_yahoo_symbol("alsp"), "ALSP.AQ")


class YahooAqConnectorTests(unittest.TestCase):
    def request(self, tickers, markets):
        return CollectionRequest(
            tickers=tickers,
            start_date=date(2026, 8, 1),
            end_date=date(2026, 8, 8),
            markets=markets,
        )

    def make_connector(self, symbol_for=None):
        from investment_monitor.sources.aq_news.yahoo.client import (
            YahooAqNewsClient,
        )

        opener = FakeOpener(
            (FIXTURES / "yahoo_aq_adb.xml").read_bytes(),
            (FIXTURES / "yahoo_aq_adb_en.xml").read_bytes(),
        )
        connector = YahooAqNewsConnector(
            client=YahooAqNewsClient(
                opener=opener,
                requests_per_second=1000,
            ),
            symbol_for=symbol_for,
        )
        return connector, opener

    def test_non_aq_markets_are_skipped_with_zero_http(self) -> None:
        connector, opener = self.make_connector()

        items = connector.collect(
            self.request(("AAPL", "VOD"), {"AAPL": "us", "VOD": "uk"})
        )

        self.assertEqual(items, [])
        self.assertEqual(connector.last_errors, ())
        self.assertEqual(opener.requested, [])

    def test_aq_maps_news_with_canonical_ticker_and_merges_bilingual(self) -> None:
        connector, opener = self.make_connector()

        items = connector.collect(
            self.request(("ADB.AQ",), {"ADB.AQ": "aq"})
        )

        by_id = {item.external_id: item for item in items}
        self.assertIn("110000601", by_id)
        bilingual = by_id["110000601"]
        self.assertEqual(bilingual.source, "yahoo_aq")
        self.assertEqual(bilingual.source_type, "news")
        self.assertEqual(bilingual.tickers, ("ADB",))
        self.assertEqual(bilingual.market, "aq")
        # Different GB/US titles on the same feed id stay one row and
        # prefer the en-US wording, flagged as en+gb.
        self.assertEqual(
            bilingual.title,
            "Adnams raises funds for new brewery",
        )
        self.assertEqual(bilingual.raw_metadata["langs"], "en+gb")
        gb_only = by_id["110000602"]
        self.assertEqual(gb_only.raw_metadata["langs"], "en-GB")
        merged = by_id["110000604"]
        self.assertEqual(merged.title, "AQSE growth stocks gain as investors rotate")
        self.assertEqual(merged.raw_metadata["langs"], "en-US")
        self.assertEqual(len(items), 3)
        self.assertIn("s=ADB.AQ", opener.requested[0])
        self.assertIn("lang=en-US", opener.requested[1])

    def test_symbol_for_injection_is_used(self) -> None:
        connector, opener = self.make_connector(
            symbol_for=lambda code: f"{code}.TEST"
        )

        connector.collect(self.request(("ADB",), {"ADB": "aq"}))

        self.assertIn("s=ADB.TEST", opener.requested[0])

    def test_single_ticker_failure_raises_and_records_error(self) -> None:
        from investment_monitor.sources.aq_news.yahoo.client import (
            YahooAqNewsClient,
        )

        def failing_opener(request, timeout=None):
            raise YahooAqNewsRequestError("yahoo blocked")

        connector = YahooAqNewsConnector(
            client=YahooAqNewsClient(
                opener=failing_opener,
                requests_per_second=1000,
            )
        )

        with self.assertRaises(YahooAqNewsRequestError):
            connector.collect(self.request(("ADB",), {"ADB": "aq"}))

        self.assertEqual(len(connector.last_errors), 1)
        self.assertEqual(connector.last_errors[0][0], "ADB")

    def test_registry_registers_yahoo_aq_without_secret_field(self) -> None:
        registry = create_default_registry()

        self.assertIsNotNone(registry.factory_for("yahoo_aq"))
        self.assertEqual(registry.secret_fields_for("yahoo_aq"), ())


if __name__ == "__main__":
    unittest.main()
