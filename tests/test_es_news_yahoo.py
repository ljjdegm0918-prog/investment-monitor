from datetime import date, datetime, timezone
from pathlib import Path
import unittest

from investment_monitor import (
    CollectionRequest,
    YahooEsNewsConnector,
    YahooEsNewsDataError,
    YahooEsNewsRequestError,
)
from investment_monitor.registry import create_default_registry


FIXTURES = Path(__file__).parent / "fixtures" / "es_news"


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
    def __init__(self, es: bytes, en: bytes) -> None:
        self.es = es
        self.en = en
        self.requested: list = []

    def __call__(self, request, timeout=None):
        url = request.full_url
        self.requested.append(url)
        body = self.es if "lang=es-ES" in url else self.en
        return FakeResponse(body)


class YahooEsClientTests(unittest.TestCase):
    def test_parses_rss_and_filters_dates(self) -> None:
        from investment_monitor.sources.es_news.yahoo.client import (
            YahooEsNewsClient,
            _parse_rss,
        )

        body = (FIXTURES / "yahoo_es_san.xml").read_bytes()
        records = _parse_rss(
            body,
            start_date=date(2026, 8, 1),
            end_date=date(2026, 8, 8),
        )

        self.assertEqual(len(records), 2)
        first = records[0]
        self.assertEqual(first["external_id"], "110000401")
        self.assertEqual(
            first["title"],
            "Santander amplia su programa de recompra",
        )
        self.assertEqual(
            first["published"],
            datetime(2026, 8, 5, 8, 30, tzinfo=timezone.utc),
        )

        opener = FakeOpener(body, b"")
        client = YahooEsNewsClient(
            opener=opener,
            requests_per_second=1000,
        )
        fetched = client.fetch_news(
            "SAN.MC",
            date(2026, 8, 1),
            date(2026, 8, 8),
        )
        self.assertEqual(len(fetched), 2)
        self.assertIn("s=SAN.MC", opener.requested[0])
        self.assertIn("region=ES", opener.requested[0])
        self.assertIn("lang=es-ES", opener.requested[0])

    def test_malformed_feed_raises_data_error(self) -> None:
        from investment_monitor.sources.es_news.yahoo.client import _parse_rss

        with self.assertRaises(YahooEsNewsDataError):
            _parse_rss(
                b"<html><body>blocked</body></html>",
                start_date=date(2026, 8, 1),
                end_date=date(2026, 8, 8),
            )


class YahooEsSymbolTests(unittest.TestCase):
    def test_symbol_appends_mc_suffix(self) -> None:
        from investment_monitor.sources.es_news.symbols import es_yahoo_symbol

        self.assertEqual(es_yahoo_symbol("SAN"), "SAN.MC")
        self.assertEqual(es_yahoo_symbol("tef"), "TEF.MC")


class YahooEsConnectorTests(unittest.TestCase):
    def request(self, tickers, markets):
        return CollectionRequest(
            tickers=tickers,
            start_date=date(2026, 8, 1),
            end_date=date(2026, 8, 8),
            markets=markets,
        )

    def make_connector(self, symbol_for=None):
        from investment_monitor.sources.es_news.yahoo.client import (
            YahooEsNewsClient,
        )

        opener = FakeOpener(
            (FIXTURES / "yahoo_es_san.xml").read_bytes(),
            (FIXTURES / "yahoo_es_san_en.xml").read_bytes(),
        )
        connector = YahooEsNewsConnector(
            client=YahooEsNewsClient(
                opener=opener,
                requests_per_second=1000,
            ),
            symbol_for=symbol_for,
        )
        return connector, opener

    def test_non_es_markets_are_skipped_with_zero_http(self) -> None:
        connector, opener = self.make_connector()

        items = connector.collect(
            self.request(("AAPL", "VOD"), {"AAPL": "us", "VOD": "uk"})
        )

        self.assertEqual(items, [])
        self.assertEqual(connector.last_errors, ())
        self.assertEqual(opener.requested, [])

    def test_es_maps_news_with_canonical_ticker_and_merges_bilingual(self) -> None:
        connector, opener = self.make_connector()

        items = connector.collect(
            self.request(("SAN.MC",), {"SAN.MC": "es"})
        )

        by_id = {item.external_id: item for item in items}
        self.assertIn("110000401", by_id)
        same = by_id["110000401"]
        self.assertEqual(same.source, "yahoo_es")
        self.assertEqual(same.source_type, "news")
        self.assertEqual(same.tickers, ("SAN",))
        self.assertEqual(same.market, "es")
        self.assertEqual(
            same.title,
            "Santander amplia su programa de recompra",
        )
        self.assertEqual(same.raw_metadata["langs"], "es")
        merged = by_id["110000404"]
        self.assertEqual(
            merged.title,
            "Santander completes Webster Financial purchase",
        )
        self.assertEqual(merged.raw_metadata["langs"], "en")
        merged_es = by_id["110000402"]
        self.assertEqual(merged_es.raw_metadata["langs"], "en+es")
        self.assertEqual(
            merged_es.title,
            "Spanish stock market closes higher",
        )
        self.assertIn("s=SAN.MC", opener.requested[0])

    def test_symbol_for_injection_is_used(self) -> None:
        connector, opener = self.make_connector(
            symbol_for=lambda code: f"{code}.TEST"
        )

        connector.collect(self.request(("SAN",), {"SAN": "es"}))

        self.assertIn("s=SAN.TEST", opener.requested[0])

    def test_single_ticker_failure_raises_and_records_error(self) -> None:
        from investment_monitor.sources.es_news.yahoo.client import (
            YahooEsNewsClient,
        )

        def failing_opener(request, timeout=None):
            raise YahooEsNewsRequestError("yahoo blocked")

        connector = YahooEsNewsConnector(
            client=YahooEsNewsClient(
                opener=failing_opener,
                requests_per_second=1000,
            )
        )

        with self.assertRaises(YahooEsNewsRequestError):
            connector.collect(self.request(("SAN",), {"SAN": "es"}))

        self.assertEqual(len(connector.last_errors), 1)
        self.assertEqual(connector.last_errors[0][0], "SAN")

    def test_registry_registers_yahoo_es_without_secret_field(self) -> None:
        registry = create_default_registry()

        self.assertIsNotNone(registry.factory_for("yahoo_es"))
        self.assertEqual(registry.secret_fields_for("yahoo_es"), ())


if __name__ == "__main__":
    unittest.main()
