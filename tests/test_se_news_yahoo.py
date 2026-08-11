from datetime import date, datetime, timezone
from pathlib import Path
import unittest

from investment_monitor import (
    CollectionRequest,
    YahooSeNewsConnector,
    YahooSeNewsDataError,
    YahooSeNewsRequestError,
)
from investment_monitor.registry import create_default_registry


FIXTURES = Path(__file__).parent / "fixtures" / "se_news"


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
    def __init__(self, sv: bytes, en: bytes) -> None:
        self.sv = sv
        self.en = en
        self.requested: list = []

    def __call__(self, request, timeout=None):
        url = request.full_url
        self.requested.append(url)
        body = self.sv if "lang=sv-SE" in url else self.en
        return FakeResponse(body)


class YahooSeClientTests(unittest.TestCase):
    def test_parses_rss_and_filters_dates(self) -> None:
        from investment_monitor.sources.se_news.yahoo.client import (
            YahooSeNewsClient,
            _parse_rss,
        )

        body = (FIXTURES / "yahoo_se_ericb.xml").read_bytes()
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
            "Ericsson redovisar rekordkvartal",
        )
        self.assertEqual(
            first["published"],
            datetime(2026, 8, 5, 8, 30, tzinfo=timezone.utc),
        )

        opener = FakeOpener(body, b"")
        client = YahooSeNewsClient(
            opener=opener,
            requests_per_second=1000,
        )
        fetched = client.fetch_news(
            "ERIC-B.ST",
            date(2026, 8, 1),
            date(2026, 8, 8),
        )
        self.assertEqual(len(fetched), 2)
        self.assertIn("s=ERIC-B.ST", opener.requested[0])
        self.assertIn("region=SE", opener.requested[0])
        self.assertIn("lang=sv-SE", opener.requested[0])

    def test_malformed_feed_raises_data_error(self) -> None:
        from investment_monitor.sources.se_news.yahoo.client import _parse_rss

        with self.assertRaises(YahooSeNewsDataError):
            _parse_rss(
                b"<html><body>blocked</body></html>",
                start_date=date(2026, 8, 1),
                end_date=date(2026, 8, 8),
            )


class YahooSeSymbolTests(unittest.TestCase):
    def test_symbol_appends_wa_suffix(self) -> None:
        from investment_monitor.sources.se_news.symbols import se_yahoo_symbol

        self.assertEqual(se_yahoo_symbol("ERIC-B"), "ERIC-B.ST")
        self.assertEqual(se_yahoo_symbol("volv-b"), "VOLV-B.ST")


class YahooSeConnectorTests(unittest.TestCase):
    def request(self, tickers, markets):
        return CollectionRequest(
            tickers=tickers,
            start_date=date(2026, 8, 1),
            end_date=date(2026, 8, 8),
            markets=markets,
        )

    def make_connector(self, symbol_for=None):
        from investment_monitor.sources.se_news.yahoo.client import (
            YahooSeNewsClient,
        )

        opener = FakeOpener(
            (FIXTURES / "yahoo_se_ericb.xml").read_bytes(),
            (FIXTURES / "yahoo_se_ericb_en.xml").read_bytes(),
        )
        connector = YahooSeNewsConnector(
            client=YahooSeNewsClient(
                opener=opener,
                requests_per_second=1000,
            ),
            symbol_for=symbol_for,
        )
        return connector, opener

    def test_non_se_markets_are_skipped_with_zero_http(self) -> None:
        connector, opener = self.make_connector()

        items = connector.collect(
            self.request(("AAPL", "VOD"), {"AAPL": "us", "VOD": "uk"})
        )

        self.assertEqual(items, [])
        self.assertEqual(connector.last_errors, ())
        self.assertEqual(opener.requested, [])

    def test_se_maps_news_with_canonical_ticker_and_merges_bilingual(self) -> None:
        connector, opener = self.make_connector()

        items = connector.collect(
            self.request(("ERIC-B.ST",), {"ERIC-B.ST": "se"})
        )

        by_id = {item.external_id: item for item in items}
        self.assertIn("110000601", by_id)
        same = by_id["110000601"]
        self.assertEqual(same.source, "yahoo_se")
        self.assertEqual(same.source_type, "news")
        self.assertEqual(same.tickers, ("ERIC-B",))
        self.assertEqual(same.market, "se")
        self.assertEqual(same.raw_metadata["langs"], "sv")
        merged = by_id["110000604"]
        self.assertEqual(merged.title, "Stockholm stocks rally on tech gains")
        self.assertEqual(merged.raw_metadata["langs"], "en")
        merged_sv = by_id["110000602"]
        self.assertEqual(merged_sv.raw_metadata["langs"], "en+sv")
        self.assertEqual(
            merged_sv.title,
            "Swedish stocks rally on tech gains",
        )
        self.assertIn("s=ERIC-B.ST", opener.requested[0])
        for item in items:
            self.assertNotIn("provenance_schema_version", item.raw_metadata)
            self.assertNotIn("official_source_id", item.raw_metadata)
            self.assertNotIn("official_source_url", item.raw_metadata)

    def test_symbol_for_injection_is_used(self) -> None:
        connector, opener = self.make_connector(
            symbol_for=lambda code: f"{code}.TEST"
        )

        connector.collect(self.request(("ERIC-B",), {"ERIC-B": "se"}))

        self.assertIn("s=ERIC-B.TEST", opener.requested[0])

    def test_single_ticker_failure_raises_and_records_error(self) -> None:
        from investment_monitor.sources.se_news.yahoo.client import (
            YahooSeNewsClient,
        )

        def failing_opener(request, timeout=None):
            raise YahooSeNewsRequestError("yahoo blocked")

        connector = YahooSeNewsConnector(
            client=YahooSeNewsClient(
                opener=failing_opener,
                requests_per_second=1000,
            )
        )

        with self.assertRaises(YahooSeNewsRequestError):
            connector.collect(self.request(("ERIC-B",), {"ERIC-B": "se"}))

        self.assertEqual(len(connector.last_errors), 1)
        self.assertEqual(connector.last_errors[0][0], "ERIC-B")

    def test_registry_registers_yahoo_se_without_secret_field(self) -> None:
        registry = create_default_registry()

        self.assertIsNotNone(registry.factory_for("yahoo_se"))
        self.assertEqual(registry.secret_fields_for("yahoo_se"), ())


if __name__ == "__main__":
    unittest.main()
