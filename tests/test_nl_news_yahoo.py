from datetime import date, datetime, timezone
from pathlib import Path
import unittest

from investment_monitor import (
    CollectionRequest,
    YahooNlNewsConnector,
    YahooNlNewsDataError,
    YahooNlNewsRequestError,
)
from investment_monitor.registry import create_default_registry


FIXTURES = Path(__file__).parent / "fixtures" / "nl_news"


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
    def __init__(self, nl: bytes, en: bytes) -> None:
        self.nl = nl
        self.en = en
        self.requested: list = []

    def __call__(self, request, timeout=None):
        url = request.full_url
        self.requested.append(url)
        body = self.nl if "lang=nl-NL" in url else self.en
        return FakeResponse(body)


class YahooNlClientTests(unittest.TestCase):
    def test_parses_rss_and_filters_dates(self) -> None:
        from investment_monitor.sources.nl_news.yahoo.client import (
            YahooNlNewsClient,
            _parse_rss,
        )

        body = (FIXTURES / "yahoo_nl_asml.xml").read_bytes()
        records = _parse_rss(
            body,
            start_date=date(2026, 8, 1),
            end_date=date(2026, 8, 8),
        )

        self.assertEqual(len(records), 2)
        first = records[0]
        self.assertEqual(first["external_id"], "110000301")
        self.assertEqual(first["title"], "ASML boekt recordwinst in tweede kwartaal")
        self.assertEqual(
            first["published"],
            datetime(2026, 8, 5, 8, 30, tzinfo=timezone.utc),
        )

        opener = FakeOpener(body, b"")
        client = YahooNlNewsClient(
            opener=opener,
            requests_per_second=1000,
        )
        fetched = client.fetch_news(
            "ASML.AS",
            date(2026, 8, 1),
            date(2026, 8, 8),
        )
        self.assertEqual(len(fetched), 2)
        self.assertIn("s=ASML.AS", opener.requested[0])
        self.assertIn("region=NL", opener.requested[0])
        self.assertIn("lang=nl-NL", opener.requested[0])

    def test_empty_channel_returns_empty_list(self) -> None:
        from investment_monitor.sources.nl_news.yahoo.client import _parse_rss

        body = b'<?xml version="1.0"?><rss version="2.0"><channel><title>x</title></channel></rss>'
        records = _parse_rss(
            body,
            start_date=date(2026, 8, 1),
            end_date=date(2026, 8, 8),
        )

        self.assertEqual(records, [])

    def test_malformed_feed_raises_data_error(self) -> None:
        from investment_monitor.sources.nl_news.yahoo.client import _parse_rss

        with self.assertRaises(YahooNlNewsDataError):
            _parse_rss(
                b"<html><body>blocked</body></html>",
                start_date=date(2026, 8, 1),
                end_date=date(2026, 8, 8),
            )


class YahooNlSymbolTests(unittest.TestCase):
    def test_symbol_appends_as_suffix(self) -> None:
        from investment_monitor.sources.nl_news.symbols import nl_yahoo_symbol

        self.assertEqual(nl_yahoo_symbol("ASML"), "ASML.AS")
        self.assertEqual(nl_yahoo_symbol("inga"), "INGA.AS")


class YahooNlConnectorTests(unittest.TestCase):
    def request(self, tickers, markets):
        return CollectionRequest(
            tickers=tickers,
            start_date=date(2026, 8, 1),
            end_date=date(2026, 8, 8),
            markets=markets,
        )

    def make_connector(self, symbol_for=None):
        from investment_monitor.sources.nl_news.yahoo.client import (
            YahooNlNewsClient,
        )

        opener = FakeOpener(
            (FIXTURES / "yahoo_nl_asml.xml").read_bytes(),
            (FIXTURES / "yahoo_nl_asml_en.xml").read_bytes(),
        )
        connector = YahooNlNewsConnector(
            client=YahooNlNewsClient(
                opener=opener,
                requests_per_second=1000,
            ),
            symbol_for=symbol_for,
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

    def test_nl_maps_news_with_canonical_ticker_and_merges_bilingual(self) -> None:
        connector, opener = self.make_connector()

        items = connector.collect(
            self.request(("ASML.AS",), {"ASML.AS": "nl"})
        )

        by_id = {item.external_id: item for item in items}
        self.assertIn("110000301", by_id)
        merged = by_id["110000301"]
        self.assertEqual(merged.source, "yahoo_nl")
        self.assertEqual(merged.source_type, "news")
        self.assertEqual(merged.tickers, ("ASML",))
        self.assertEqual(merged.market, "nl")
        self.assertEqual(merged.title, "ASML posts record profit in Q2")
        self.assertEqual(merged.raw_metadata["langs"], "en+nl")
        self.assertEqual(
            merged.raw_metadata["title_nl"],
            "ASML boekt recordwinst in tweede kwartaal",
        )
        en_only = by_id["110000304"]
        self.assertEqual(en_only.raw_metadata["langs"], "en")
        nl_only = by_id["110000302"]
        self.assertEqual(nl_only.raw_metadata["langs"], "nl")
        self.assertIn("s=ASML.AS", opener.requested[0])

    def test_symbol_for_injection_is_used(self) -> None:
        connector, opener = self.make_connector(
            symbol_for=lambda code: f"{code}.TEST"
        )

        connector.collect(self.request(("ASML",), {"ASML": "nl"}))

        self.assertIn("s=ASML.TEST", opener.requested[0])

    def test_single_ticker_failure_raises_and_records_error(self) -> None:
        from investment_monitor.sources.nl_news.yahoo.client import (
            YahooNlNewsClient,
        )

        def failing_opener(request, timeout=None):
            raise YahooNlNewsRequestError("yahoo blocked")

        connector = YahooNlNewsConnector(
            client=YahooNlNewsClient(
                opener=failing_opener,
                requests_per_second=1000,
            )
        )

        with self.assertRaises(YahooNlNewsRequestError):
            connector.collect(self.request(("ASML",), {"ASML": "nl"}))

        self.assertEqual(len(connector.last_errors), 1)
        self.assertEqual(connector.last_errors[0][0], "ASML")

    def test_registry_registers_yahoo_nl_without_secret_field(self) -> None:
        registry = create_default_registry()

        self.assertIsNotNone(registry.factory_for("yahoo_nl"))
        self.assertEqual(registry.secret_fields_for("yahoo_nl"), ())


if __name__ == "__main__":
    unittest.main()
