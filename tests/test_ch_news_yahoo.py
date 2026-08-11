from datetime import date, datetime, timezone
from pathlib import Path
import unittest

from investment_monitor import (
    CollectionRequest,
    YahooChNewsConnector,
    YahooChNewsDataError,
    YahooChNewsRequestError,
)
from investment_monitor.registry import create_default_registry


FIXTURES = Path(__file__).parent / "fixtures" / "ch_news"


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
    def __init__(self, de: bytes, en: bytes) -> None:
        self.de = de
        self.en = en
        self.requested: list = []

    def __call__(self, request, timeout=None):
        url = request.full_url
        self.requested.append(url)
        body = self.de if "lang=de-CH" in url else self.en
        return FakeResponse(body)


class YahooChClientTests(unittest.TestCase):
    def test_parses_rss_and_filters_dates(self) -> None:
        from investment_monitor.sources.ch_news.yahoo.client import (
            YahooChNewsClient,
            _parse_rss,
        )

        body = (FIXTURES / "yahoo_ch_nesn.xml").read_bytes()
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
            "Nestle meldet starkes Quartalsergebnis",
        )
        self.assertEqual(
            first["published"],
            datetime(2026, 8, 5, 8, 30, tzinfo=timezone.utc),
        )

        opener = FakeOpener(body, b"")
        client = YahooChNewsClient(
            opener=opener,
            requests_per_second=1000,
        )
        fetched = client.fetch_news(
            "NESN.SW",
            date(2026, 8, 1),
            date(2026, 8, 8),
        )
        self.assertEqual(len(fetched), 2)
        self.assertIn("s=NESN.SW", opener.requested[0])
        self.assertIn("region=CH", opener.requested[0])
        self.assertIn("lang=de-CH", opener.requested[0])

    def test_malformed_feed_raises_data_error(self) -> None:
        from investment_monitor.sources.ch_news.yahoo.client import _parse_rss

        with self.assertRaises(YahooChNewsDataError):
            _parse_rss(
                b"<html><body>blocked</body></html>",
                start_date=date(2026, 8, 1),
                end_date=date(2026, 8, 8),
            )


class YahooChSymbolTests(unittest.TestCase):
    def test_symbol_appends_sw_suffix(self) -> None:
        from investment_monitor.sources.ch_news.symbols import ch_yahoo_symbol

        self.assertEqual(ch_yahoo_symbol("NESN"), "NESN.SW")
        self.assertEqual(ch_yahoo_symbol("rog"), "ROG.SW")


class YahooChConnectorTests(unittest.TestCase):
    def request(self, tickers, markets):
        return CollectionRequest(
            tickers=tickers,
            start_date=date(2026, 8, 1),
            end_date=date(2026, 8, 8),
            markets=markets,
        )

    def make_connector(self, symbol_for=None):
        from investment_monitor.sources.ch_news.yahoo.client import (
            YahooChNewsClient,
        )

        opener = FakeOpener(
            (FIXTURES / "yahoo_ch_nesn.xml").read_bytes(),
            (FIXTURES / "yahoo_ch_nesn_en.xml").read_bytes(),
        )
        connector = YahooChNewsConnector(
            client=YahooChNewsClient(
                opener=opener,
                requests_per_second=1000,
            ),
            symbol_for=symbol_for,
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

    def test_ch_maps_news_with_canonical_ticker_and_merges_bilingual(self) -> None:
        connector, opener = self.make_connector()

        items = connector.collect(
            self.request(("NESN.SW",), {"NESN.SW": "ch"})
        )

        by_id = {item.external_id: item for item in items}
        self.assertIn("110000601", by_id)
        same = by_id["110000601"]
        self.assertEqual(same.source, "yahoo_ch")
        self.assertEqual(same.source_type, "news")
        self.assertEqual(same.tickers, ("NESN",))
        self.assertEqual(same.market, "ch")
        self.assertEqual(same.raw_metadata["langs"], "de")
        merged = by_id["110000604"]
        self.assertEqual(merged.title, "Nestle buys specialty coffee brand")
        self.assertEqual(merged.raw_metadata["langs"], "en")
        merged_de = by_id["110000602"]
        self.assertEqual(merged_de.raw_metadata["langs"], "en+de")
        self.assertEqual(
            merged_de.title,
            "Swiss shares end the week higher",
        )
        self.assertIn("s=NESN.SW", opener.requested[0])

    def test_symbol_for_injection_is_used(self) -> None:
        connector, opener = self.make_connector(
            symbol_for=lambda code: f"{code}.TEST"
        )

        connector.collect(self.request(("NESN",), {"NESN": "ch"}))

        self.assertIn("s=NESN.TEST", opener.requested[0])

    def test_single_ticker_failure_raises_and_records_error(self) -> None:
        from investment_monitor.sources.ch_news.yahoo.client import (
            YahooChNewsClient,
        )

        def failing_opener(request, timeout=None):
            raise YahooChNewsRequestError("yahoo blocked")

        connector = YahooChNewsConnector(
            client=YahooChNewsClient(
                opener=failing_opener,
                requests_per_second=1000,
            )
        )

        with self.assertRaises(YahooChNewsRequestError):
            connector.collect(self.request(("NESN",), {"NESN": "ch"}))

        self.assertEqual(len(connector.last_errors), 1)
        self.assertEqual(connector.last_errors[0][0], "NESN")

    def test_registry_registers_yahoo_ch_without_secret_field(self) -> None:
        registry = create_default_registry()

        self.assertIsNotNone(registry.factory_for("yahoo_ch"))
        self.assertEqual(registry.secret_fields_for("yahoo_ch"), ())


if __name__ == "__main__":
    unittest.main()
