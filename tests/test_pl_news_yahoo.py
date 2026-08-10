from datetime import date, datetime, timezone
from pathlib import Path
import unittest

from investment_monitor import (
    CollectionRequest,
    YahooPlNewsConnector,
    YahooPlNewsDataError,
    YahooPlNewsRequestError,
)
from investment_monitor.registry import create_default_registry


FIXTURES = Path(__file__).parent / "fixtures" / "pl_news"


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
    def __init__(self, pl: bytes, en: bytes) -> None:
        self.pl = pl
        self.en = en
        self.requested: list = []

    def __call__(self, request, timeout=None):
        url = request.full_url
        self.requested.append(url)
        body = self.pl if "lang=pl-PL" in url else self.en
        return FakeResponse(body)


class YahooPlClientTests(unittest.TestCase):
    def test_parses_rss_and_filters_dates(self) -> None:
        from investment_monitor.sources.pl_news.yahoo.client import (
            YahooPlNewsClient,
            _parse_rss,
        )

        body = (FIXTURES / "yahoo_pl_pko.xml").read_bytes()
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
            "PKO Bank Polski raportuje rekordowy zysk kwartalny",
        )
        self.assertEqual(
            first["published"],
            datetime(2026, 8, 5, 8, 30, tzinfo=timezone.utc),
        )

        opener = FakeOpener(body, b"")
        client = YahooPlNewsClient(
            opener=opener,
            requests_per_second=1000,
        )
        fetched = client.fetch_news(
            "PKO.WA",
            date(2026, 8, 1),
            date(2026, 8, 8),
        )
        self.assertEqual(len(fetched), 2)
        self.assertIn("s=PKO.WA", opener.requested[0])
        self.assertIn("region=PL", opener.requested[0])
        self.assertIn("lang=pl-PL", opener.requested[0])

    def test_malformed_feed_raises_data_error(self) -> None:
        from investment_monitor.sources.pl_news.yahoo.client import _parse_rss

        with self.assertRaises(YahooPlNewsDataError):
            _parse_rss(
                b"<html><body>blocked</body></html>",
                start_date=date(2026, 8, 1),
                end_date=date(2026, 8, 8),
            )


class YahooPlSymbolTests(unittest.TestCase):
    def test_symbol_appends_wa_suffix(self) -> None:
        from investment_monitor.sources.pl_news.symbols import pl_yahoo_symbol

        self.assertEqual(pl_yahoo_symbol("PKO"), "PKO.WA")
        self.assertEqual(pl_yahoo_symbol("pkn"), "PKN.WA")


class YahooPlConnectorTests(unittest.TestCase):
    def request(self, tickers, markets):
        return CollectionRequest(
            tickers=tickers,
            start_date=date(2026, 8, 1),
            end_date=date(2026, 8, 8),
            markets=markets,
        )

    def make_connector(self, symbol_for=None):
        from investment_monitor.sources.pl_news.yahoo.client import (
            YahooPlNewsClient,
        )

        opener = FakeOpener(
            (FIXTURES / "yahoo_pl_pko.xml").read_bytes(),
            (FIXTURES / "yahoo_pl_pko_en.xml").read_bytes(),
        )
        connector = YahooPlNewsConnector(
            client=YahooPlNewsClient(
                opener=opener,
                requests_per_second=1000,
            ),
            symbol_for=symbol_for,
        )
        return connector, opener

    def test_non_pl_markets_are_skipped_with_zero_http(self) -> None:
        connector, opener = self.make_connector()

        items = connector.collect(
            self.request(("AAPL", "VOD"), {"AAPL": "us", "VOD": "uk"})
        )

        self.assertEqual(items, [])
        self.assertEqual(connector.last_errors, ())
        self.assertEqual(opener.requested, [])

    def test_pl_maps_news_with_canonical_ticker_and_merges_bilingual(self) -> None:
        connector, opener = self.make_connector()

        items = connector.collect(
            self.request(("PKO.WA",), {"PKO.WA": "pl"})
        )

        by_id = {item.external_id: item for item in items}
        self.assertIn("110000601", by_id)
        same = by_id["110000601"]
        self.assertEqual(same.source, "yahoo_pl")
        self.assertEqual(same.source_type, "news")
        self.assertEqual(same.tickers, ("PKO",))
        self.assertEqual(same.market, "pl")
        self.assertEqual(same.raw_metadata["langs"], "pl")
        merged = by_id["110000604"]
        self.assertEqual(merged.title, "Warsaw stocks rally on rate cut hopes")
        self.assertEqual(merged.raw_metadata["langs"], "en")
        merged_pl = by_id["110000602"]
        self.assertEqual(merged_pl.raw_metadata["langs"], "en+pl")
        self.assertEqual(
            merged_pl.title,
            "Polish banks post higher profits",
        )
        self.assertIn("s=PKO.WA", opener.requested[0])

    def test_symbol_for_injection_is_used(self) -> None:
        connector, opener = self.make_connector(
            symbol_for=lambda code: f"{code}.TEST"
        )

        connector.collect(self.request(("PKO",), {"PKO": "pl"}))

        self.assertIn("s=PKO.TEST", opener.requested[0])

    def test_single_ticker_failure_raises_and_records_error(self) -> None:
        from investment_monitor.sources.pl_news.yahoo.client import (
            YahooPlNewsClient,
        )

        def failing_opener(request, timeout=None):
            raise YahooPlNewsRequestError("yahoo blocked")

        connector = YahooPlNewsConnector(
            client=YahooPlNewsClient(
                opener=failing_opener,
                requests_per_second=1000,
            )
        )

        with self.assertRaises(YahooPlNewsRequestError):
            connector.collect(self.request(("PKO",), {"PKO": "pl"}))

        self.assertEqual(len(connector.last_errors), 1)
        self.assertEqual(connector.last_errors[0][0], "PKO")

    def test_registry_registers_yahoo_pl_without_secret_field(self) -> None:
        registry = create_default_registry()

        self.assertIsNotNone(registry.factory_for("yahoo_pl"))
        self.assertEqual(registry.secret_fields_for("yahoo_pl"), ())


if __name__ == "__main__":
    unittest.main()
