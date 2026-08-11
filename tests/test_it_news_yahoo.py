from datetime import date, datetime, timezone
from pathlib import Path
import unittest

from investment_monitor import (
    CollectionRequest,
    YahooItNewsConnector,
    YahooItNewsDataError,
    YahooItNewsRequestError,
)
from investment_monitor.registry import create_default_registry


FIXTURES = Path(__file__).parent / "fixtures" / "it_news"


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
    def __init__(self, it: bytes, en: bytes) -> None:
        self.it = it
        self.en = en
        self.requested: list = []

    def __call__(self, request, timeout=None):
        url = request.full_url
        self.requested.append(url)
        body = self.it if "lang=it-IT" in url else self.en
        return FakeResponse(body)


class YahooItClientTests(unittest.TestCase):
    def test_parses_rss_and_filters_dates(self) -> None:
        from investment_monitor.sources.it_news.yahoo.client import (
            YahooItNewsClient,
            _parse_rss,
        )

        body = (FIXTURES / "yahoo_it_eni.xml").read_bytes()
        records = _parse_rss(
            body,
            start_date=date(2026, 8, 1),
            end_date=date(2026, 8, 8),
        )

        self.assertEqual(len(records), 2)
        first = records[0]
        self.assertEqual(first["external_id"], "110000401")
        self.assertEqual(first["title"], "Eni alza le previsioni sul flusso di cassa")
        self.assertEqual(
            first["published"],
            datetime(2026, 8, 5, 8, 30, tzinfo=timezone.utc),
        )

        opener = FakeOpener(body, b"")
        client = YahooItNewsClient(
            opener=opener,
            requests_per_second=1000,
        )
        fetched = client.fetch_news(
            "ENI.MI",
            date(2026, 8, 1),
            date(2026, 8, 8),
        )
        self.assertEqual(len(fetched), 2)
        self.assertIn("s=ENI.MI", opener.requested[0])
        self.assertIn("region=IT", opener.requested[0])
        self.assertIn("lang=it-IT", opener.requested[0])

    def test_empty_channel_returns_empty_list(self) -> None:
        from investment_monitor.sources.it_news.yahoo.client import _parse_rss

        body = b'<?xml version="1.0"?><rss version="2.0"><channel><title>x</title></channel></rss>'
        records = _parse_rss(
            body,
            start_date=date(2026, 8, 1),
            end_date=date(2026, 8, 8),
        )

        self.assertEqual(records, [])

    def test_malformed_feed_raises_data_error(self) -> None:
        from investment_monitor.sources.it_news.yahoo.client import _parse_rss

        with self.assertRaises(YahooItNewsDataError):
            _parse_rss(
                b"<html><body>blocked</body></html>",
                start_date=date(2026, 8, 1),
                end_date=date(2026, 8, 8),
            )


class YahooItSymbolTests(unittest.TestCase):
    def test_symbol_appends_mi_suffix(self) -> None:
        from investment_monitor.sources.it_news.symbols import it_yahoo_symbol

        self.assertEqual(it_yahoo_symbol("ENI"), "ENI.MI")
        self.assertEqual(it_yahoo_symbol("ucg"), "UCG.MI")


class YahooItConnectorTests(unittest.TestCase):
    def request(self, tickers, markets):
        return CollectionRequest(
            tickers=tickers,
            start_date=date(2026, 8, 1),
            end_date=date(2026, 8, 8),
            markets=markets,
        )

    def make_connector(self, symbol_for=None):
        from investment_monitor.sources.it_news.yahoo.client import (
            YahooItNewsClient,
        )

        opener = FakeOpener(
            (FIXTURES / "yahoo_it_eni.xml").read_bytes(),
            (FIXTURES / "yahoo_it_eni_en.xml").read_bytes(),
        )
        connector = YahooItNewsConnector(
            client=YahooItNewsClient(
                opener=opener,
                requests_per_second=1000,
            ),
            symbol_for=symbol_for,
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

    def test_it_maps_news_with_canonical_ticker_and_merges_bilingual(self) -> None:
        connector, opener = self.make_connector()

        items = connector.collect(
            self.request(("ENI.MI",), {"ENI.MI": "it"})
        )

        by_id = {item.external_id: item for item in items}
        self.assertIn("110000401", by_id)
        merged = by_id["110000401"]
        self.assertEqual(merged.source, "yahoo_it")
        self.assertEqual(merged.source_type, "news")
        self.assertEqual(merged.tickers, ("ENI",))
        self.assertEqual(merged.market, "it")
        self.assertEqual(merged.title, "Eni raises cash flow guidance")
        self.assertEqual(merged.raw_metadata["langs"], "en+it")
        en_only = by_id["110000404"]
        self.assertEqual(en_only.raw_metadata["langs"], "en")
        it_only = by_id["110000402"]
        self.assertEqual(it_only.raw_metadata["langs"], "it")
        self.assertIn("s=ENI.MI", opener.requested[0])

    def test_symbol_for_injection_is_used(self) -> None:
        connector, opener = self.make_connector(
            symbol_for=lambda code: f"{code}.TEST"
        )

        connector.collect(self.request(("ENI",), {"ENI": "it"}))

        self.assertIn("s=ENI.TEST", opener.requested[0])

    def test_single_ticker_failure_raises_and_records_error(self) -> None:
        from investment_monitor.sources.it_news.yahoo.client import (
            YahooItNewsClient,
        )

        def failing_opener(request, timeout=None):
            raise YahooItNewsRequestError("yahoo blocked")

        connector = YahooItNewsConnector(
            client=YahooItNewsClient(
                opener=failing_opener,
                requests_per_second=1000,
            )
        )

        with self.assertRaises(YahooItNewsRequestError):
            connector.collect(self.request(("ENI",), {"ENI": "it"}))

        self.assertEqual(len(connector.last_errors), 1)
        self.assertEqual(connector.last_errors[0][0], "ENI")

    def test_registry_registers_yahoo_it_without_secret_field(self) -> None:
        registry = create_default_registry()

        self.assertIsNotNone(registry.factory_for("yahoo_it"))
        self.assertEqual(registry.secret_fields_for("yahoo_it"), ())


if __name__ == "__main__":
    unittest.main()
