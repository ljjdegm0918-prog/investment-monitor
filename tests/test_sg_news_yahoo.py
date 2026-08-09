from datetime import date, datetime, timezone
from pathlib import Path
import unittest

from investment_monitor import (
    CollectionRequest,
    YahooSgNewsConnector,
    YahooSgNewsDataError,
    YahooSgNewsRequestError,
)
from investment_monitor.registry import create_default_registry


FIXTURES = Path(__file__).parent / "fixtures" / "sg_news"


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
    def __init__(self, sg: bytes, en: bytes) -> None:
        self.sg = sg
        self.en = en
        self.requested: list = []

    def __call__(self, request, timeout=None):
        url = request.full_url
        self.requested.append(url)
        body = self.sg if "lang=en-SG" in url else self.en
        return FakeResponse(body)


class YahooSgClientTests(unittest.TestCase):
    def test_parses_rss_and_filters_dates(self) -> None:
        from investment_monitor.sources.sg_news.yahoo.client import (
            YahooSgNewsClient,
            _parse_rss,
        )

        body = (FIXTURES / "yahoo_sg_d05.xml").read_bytes()
        records = _parse_rss(
            body,
            start_date=date(2026, 8, 1),
            end_date=date(2026, 8, 8),
        )

        self.assertEqual(len(records), 2)
        first = records[0]
        self.assertEqual(first["external_id"], "110000501")
        self.assertEqual(first["title"], "DBS reports record quarterly profit")
        self.assertEqual(
            first["published"],
            datetime(2026, 8, 5, 8, 30, tzinfo=timezone.utc),
        )

        opener = FakeOpener(body, b"")
        client = YahooSgNewsClient(
            opener=opener,
            requests_per_second=1000,
        )
        fetched = client.fetch_news(
            "D05.SI",
            date(2026, 8, 1),
            date(2026, 8, 8),
        )
        self.assertEqual(len(fetched), 2)
        self.assertIn("s=D05.SI", opener.requested[0])
        self.assertIn("region=SG", opener.requested[0])
        self.assertIn("lang=en-SG", opener.requested[0])

    def test_malformed_feed_raises_data_error(self) -> None:
        from investment_monitor.sources.sg_news.yahoo.client import _parse_rss

        with self.assertRaises(YahooSgNewsDataError):
            _parse_rss(
                b"<html><body>blocked</body></html>",
                start_date=date(2026, 8, 1),
                end_date=date(2026, 8, 8),
            )


class YahooSgSymbolTests(unittest.TestCase):
    def test_symbol_appends_si_suffix(self) -> None:
        from investment_monitor.sources.sg_news.symbols import sg_yahoo_symbol

        self.assertEqual(sg_yahoo_symbol("D05"), "D05.SI")
        self.assertEqual(sg_yahoo_symbol("u11"), "U11.SI")


class YahooSgConnectorTests(unittest.TestCase):
    def request(self, tickers, markets):
        return CollectionRequest(
            tickers=tickers,
            start_date=date(2026, 8, 1),
            end_date=date(2026, 8, 8),
            markets=markets,
        )

    def make_connector(self, symbol_for=None):
        from investment_monitor.sources.sg_news.yahoo.client import (
            YahooSgNewsClient,
        )

        opener = FakeOpener(
            (FIXTURES / "yahoo_sg_d05.xml").read_bytes(),
            (FIXTURES / "yahoo_sg_d05_en.xml").read_bytes(),
        )
        connector = YahooSgNewsConnector(
            client=YahooSgNewsClient(
                opener=opener,
                requests_per_second=1000,
            ),
            symbol_for=symbol_for,
        )
        return connector, opener

    def test_non_sg_markets_are_skipped_with_zero_http(self) -> None:
        connector, opener = self.make_connector()

        items = connector.collect(
            self.request(("AAPL", "VOD"), {"AAPL": "us", "VOD": "uk"})
        )

        self.assertEqual(items, [])
        self.assertEqual(connector.last_errors, ())
        self.assertEqual(opener.requested, [])

    def test_sg_maps_news_with_canonical_ticker_and_merges_bilingual(self) -> None:
        connector, opener = self.make_connector()

        items = connector.collect(
            self.request(("D05.SI",), {"D05.SI": "sg"})
        )

        by_id = {item.external_id: item for item in items}
        self.assertIn("110000501", by_id)
        same = by_id["110000501"]
        self.assertEqual(same.source, "yahoo_sg")
        self.assertEqual(same.source_type, "news")
        self.assertEqual(same.tickers, ("D05",))
        self.assertEqual(same.market, "sg")
        self.assertEqual(same.raw_metadata["langs"], "sg")
        merged = by_id["110000504"]
        self.assertEqual(merged.title, "DBS buys regional wealth manager")
        self.assertEqual(merged.raw_metadata["langs"], "en")
        merged_sg = by_id["110000502"]
        self.assertEqual(merged_sg.raw_metadata["langs"], "en+sg")
        self.assertEqual(
            merged_sg.title,
            "Singapore equities end the week higher",
        )
        self.assertIn("s=D05.SI", opener.requested[0])

    def test_symbol_for_injection_is_used(self) -> None:
        connector, opener = self.make_connector(
            symbol_for=lambda code: f"{code}.TEST"
        )

        connector.collect(self.request(("D05",), {"D05": "sg"}))

        self.assertIn("s=D05.TEST", opener.requested[0])

    def test_single_ticker_failure_raises_and_records_error(self) -> None:
        from investment_monitor.sources.sg_news.yahoo.client import (
            YahooSgNewsClient,
        )

        def failing_opener(request, timeout=None):
            raise YahooSgNewsRequestError("yahoo blocked")

        connector = YahooSgNewsConnector(
            client=YahooSgNewsClient(
                opener=failing_opener,
                requests_per_second=1000,
            )
        )

        with self.assertRaises(YahooSgNewsRequestError):
            connector.collect(self.request(("D05",), {"D05": "sg"}))

        self.assertEqual(len(connector.last_errors), 1)
        self.assertEqual(connector.last_errors[0][0], "D05")

    def test_registry_registers_yahoo_sg_without_secret_field(self) -> None:
        registry = create_default_registry()

        self.assertIsNotNone(registry.factory_for("yahoo_sg"))
        self.assertEqual(registry.secret_fields_for("yahoo_sg"), ())


if __name__ == "__main__":
    unittest.main()
