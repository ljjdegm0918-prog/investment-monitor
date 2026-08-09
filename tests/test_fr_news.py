from datetime import date, datetime, timezone
from pathlib import Path
import unittest

from investment_monitor import (
    ALLOWED_MARKETS,
    CollectionRequest,
    FinnhubNewsConnector,
    GoogleFrNewsConnector,
    GoogleFrNewsDataError,
    GoogleFrNewsRequestError,
    MARKET_FR,
    YahooFrNewsConnector,
    YahooFrNewsDataError,
    YahooFrNewsRequestError,
)
from investment_monitor.registry import create_default_registry
from investment_monitor.web_repository import normalize_fr_ticker


FIXTURES = Path(__file__).parent / "fixtures" / "fr_news"


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


class FakeBilingualOpener:
    def __init__(self, fr: bytes, en: bytes) -> None:
        self.fr = fr
        self.en = en
        self.requested: list = []

    def __call__(self, request, timeout=None):
        url = request.full_url
        self.requested.append(url)
        body = self.fr if "lang=fr-FR" in url else self.en
        return FakeResponse(body)


class YahooFrClientTests(unittest.TestCase):
    def test_parses_rss_and_filters_dates(self) -> None:
        from investment_monitor.sources.fr_news.yahoo.client import (
            YahooFrNewsClient,
            _parse_rss,
        )

        body = (FIXTURES / "yahoo_fr_mc.xml").read_bytes()
        records = _parse_rss(
            body,
            start_date=date(2026, 8, 1),
            end_date=date(2026, 8, 9),
        )

        self.assertEqual(len(records), 2)
        first = records[0]
        self.assertEqual(first["external_id"], "110000301")
        self.assertEqual(
            first["title"],
            "LVMH dépasse les attentes au premier semestre",
        )
        self.assertEqual(
            first["published"],
            datetime(2026, 8, 8, 3, 25, 44, tzinfo=timezone.utc),
        )

        opener = FakeOpener(body)
        client = YahooFrNewsClient(
            opener=opener,
            requests_per_second=1000,
        )
        fetched = client.fetch_news(
            "MC.PA",
            date(2026, 8, 1),
            date(2026, 8, 9),
        )
        self.assertEqual(len(fetched), 2)
        self.assertIn("s=MC.PA", opener.requested[0])
        self.assertIn("region=FR", opener.requested[0])
        self.assertIn("lang=fr-FR", opener.requested[0])

    def test_empty_channel_returns_empty_list(self) -> None:
        from investment_monitor.sources.fr_news.yahoo.client import _parse_rss

        body = (
            b'<?xml version="1.0"?><rss version="2.0">'
            b"<channel><title>x</title></channel></rss>"
        )
        records = _parse_rss(
            body,
            start_date=date(2026, 8, 1),
            end_date=date(2026, 8, 9),
        )

        self.assertEqual(records, [])

    def test_malformed_feed_raises_data_error(self) -> None:
        from investment_monitor.sources.fr_news.yahoo.client import _parse_rss

        with self.assertRaises(YahooFrNewsDataError):
            _parse_rss(
                b"<html><body>blocked</body></html>",
                start_date=date(2026, 8, 1),
                end_date=date(2026, 8, 9),
            )


class YahooFrSymbolTests(unittest.TestCase):
    def test_symbol_appends_pa_suffix(self) -> None:
        from investment_monitor.sources.fr_news.symbols import (
            fr_yahoo_symbol,
        )

        self.assertEqual(fr_yahoo_symbol("MC"), "MC.PA")
        self.assertEqual(fr_yahoo_symbol("mc"), "MC.PA")
        self.assertEqual(fr_yahoo_symbol("MC.PA"), "MC.PA.PA")

    def test_normalize_fr_ticker_variants(self) -> None:
        for variant, expected in (
            ("MC", "MC"),
            ("MC.PA", "MC"),
            ("mc.pa", "MC"),
            ("MC-PA", "MC"),
            ("MC PA", "MC"),
            ("MC.PA.PA", "MC"),
        ):
            self.assertEqual(normalize_fr_ticker(variant), expected)

    def test_normalize_fr_ticker_keeps_plain_input(self) -> None:
        self.assertEqual(normalize_fr_ticker("VOD"), "VOD")
        self.assertEqual(normalize_fr_ticker("PA"), "PA")
        self.assertEqual(normalize_fr_ticker("abcd"), "ABCD")


class YahooFrConnectorTests(unittest.TestCase):
    def request(self, tickers, markets):
        return CollectionRequest(
            tickers=tickers,
            start_date=date(2026, 8, 1),
            end_date=date(2026, 8, 9),
            markets=markets,
        )

    def make_connector(self, symbol_for=None):
        from investment_monitor.sources.fr_news.yahoo.client import (
            YahooFrNewsClient,
        )

        opener = FakeBilingualOpener(
            (FIXTURES / "yahoo_fr_mc.xml").read_bytes(),
            (FIXTURES / "yahoo_fr_mc_en.xml").read_bytes(),
        )
        connector = YahooFrNewsConnector(
            client=YahooFrNewsClient(
                opener=opener,
                requests_per_second=1000,
            ),
            symbol_for=symbol_for,
        )
        return connector, opener

    def test_non_fr_markets_are_skipped_with_zero_http(self) -> None:
        connector, opener = self.make_connector()

        items = connector.collect(
            self.request(("AAPL", "VOD"), {"AAPL": "us", "VOD": "uk"})
        )

        self.assertEqual(items, [])
        self.assertEqual(connector.last_errors, ())
        self.assertEqual(opener.requested, [])

    def test_fr_maps_bilingual_news_with_canonical_ticker(self) -> None:
        connector, opener = self.make_connector()

        items = connector.collect(
            self.request(("MC.PA",), {"MC.PA": "fr"})
        )

        by_id = {item.external_id: item for item in items}
        self.assertEqual(len(by_id), 3)
        merged = by_id["110000301"]
        self.assertEqual(merged.source, "yahoo_fr")
        self.assertEqual(merged.source_type, "news")
        self.assertEqual(merged.tickers, ("MC",))
        self.assertEqual(merged.market, "fr")
        self.assertEqual(
            merged.title,
            "LVMH beats expectations in first half",
        )
        self.assertEqual(
            merged.raw_metadata["title_fr"],
            "LVMH dépasse les attentes au premier semestre",
        )
        self.assertEqual(merged.raw_metadata["langs"], "en+fr")
        self.assertEqual(by_id["110000302"].raw_metadata["langs"], "fr")
        self.assertEqual(by_id["110000303"].raw_metadata["langs"], "en")
        self.assertIn("s=MC.PA", opener.requested[0])
        self.assertIn("lang=fr-FR", opener.requested[0])
        self.assertIn("lang=en-US", opener.requested[1])

    def test_symbol_for_injection_is_used(self) -> None:
        connector, opener = self.make_connector(
            symbol_for=lambda code: f"{code}.TEST"
        )

        connector.collect(self.request(("MC",), {"MC": "fr"}))

        self.assertIn("s=MC.TEST", opener.requested[0])

    def test_single_ticker_failure_raises_and_records_error(self) -> None:
        from investment_monitor.sources.fr_news.yahoo.client import (
            YahooFrNewsClient,
        )

        def failing_opener(request, timeout=None):
            raise YahooFrNewsRequestError("yahoo blocked")

        connector = YahooFrNewsConnector(
            client=YahooFrNewsClient(
                opener=failing_opener,
                requests_per_second=1000,
            )
        )

        with self.assertRaises(YahooFrNewsRequestError):
            connector.collect(self.request(("MC",), {"MC": "fr"}))

        self.assertEqual(len(connector.last_errors), 1)
        self.assertEqual(connector.last_errors[0][0], "MC")

    def test_registry_registers_yahoo_fr_without_secret_field(self) -> None:
        registry = create_default_registry()

        self.assertIsNotNone(registry.factory_for("yahoo_fr"))
        self.assertEqual(registry.secret_fields_for("yahoo_fr"), ())


class GoogleFrClientTests(unittest.TestCase):
    def test_parses_rss_and_builds_france_query(self) -> None:
        from investment_monitor.sources.fr_news.google.client import (
            GoogleFrNewsClient,
            _parse_rss,
        )

        body = (FIXTURES / "google_fr_mc.xml").read_bytes()
        records = _parse_rss(
            body,
            start_date=date(2026, 8, 1),
            end_date=date(2026, 8, 9),
        )

        self.assertEqual(len(records), 2)
        first = records[0]
        self.assertEqual(
            first["title"],
            "LVMH: les ventes progressent au premier semestre",
        )
        self.assertEqual(
            first["published"],
            datetime(2026, 8, 7, 1, 39, tzinfo=timezone.utc),
        )

        opener = FakeOpener(body)
        client = GoogleFrNewsClient(
            opener=opener,
            requests_per_second=1000,
        )
        fetched = client.fetch_news(
            "MC.PA",
            date(2026, 8, 1),
            date(2026, 8, 9),
        )
        self.assertEqual(len(fetched), 2)
        self.assertIn("q=MC.PA", opener.requested[0])
        self.assertIn("hl=fr", opener.requested[0])
        self.assertIn("gl=FR", opener.requested[0])
        self.assertIn("ceid=FR:fr", opener.requested[0])

    def test_malformed_feed_raises_data_error(self) -> None:
        from investment_monitor.sources.fr_news.google.client import _parse_rss

        with self.assertRaises(GoogleFrNewsDataError):
            _parse_rss(
                b"<html><body>blocked</body></html>",
                start_date=date(2026, 8, 1),
                end_date=date(2026, 8, 9),
            )


class GoogleFrConnectorTests(unittest.TestCase):
    def request(self, tickers, markets):
        return CollectionRequest(
            tickers=tickers,
            start_date=date(2026, 8, 1),
            end_date=date(2026, 8, 9),
            markets=markets,
        )

    def make_connector(self, symbol_for=None):
        from investment_monitor.sources.fr_news.google.client import (
            GoogleFrNewsClient,
        )

        opener = FakeOpener((FIXTURES / "google_fr_mc.xml").read_bytes())
        connector = GoogleFrNewsConnector(
            client=GoogleFrNewsClient(
                opener=opener,
                requests_per_second=1000,
            ),
            symbol_for=symbol_for,
        )
        return connector, opener

    def test_non_fr_markets_are_skipped_with_zero_http(self) -> None:
        connector, opener = self.make_connector()

        items = connector.collect(
            self.request(("AAPL", "VOD"), {"AAPL": "us", "VOD": "uk"})
        )

        self.assertEqual(items, [])
        self.assertEqual(connector.last_errors, ())
        self.assertEqual(opener.requested, [])

    def test_fr_maps_news_with_canonical_ticker(self) -> None:
        connector, opener = self.make_connector()

        items = connector.collect(
            self.request(("MC.PA",), {"MC.PA": "fr"})
        )

        self.assertEqual(len(items), 2)
        first = items[0]
        self.assertEqual(first.source, "google_news_fr")
        self.assertEqual(first.source_type, "news")
        self.assertEqual(first.tickers, ("MC",))
        self.assertEqual(first.market, "fr")
        self.assertEqual(first.raw_metadata["provider"], "google_news_rss")
        self.assertEqual(first.raw_metadata["langs"], "fr")
        self.assertIn("q=MC.PA", opener.requested[0])

    def test_symbol_for_injection_is_used(self) -> None:
        connector, opener = self.make_connector(
            symbol_for=lambda code: f"{code}.TEST"
        )

        connector.collect(self.request(("MC",), {"MC": "fr"}))

        self.assertIn("q=MC.TEST", opener.requested[0])

    def test_single_ticker_failure_raises_and_records_error(self) -> None:
        from investment_monitor.sources.fr_news.google.client import (
            GoogleFrNewsClient,
        )

        def failing_opener(request, timeout=None):
            raise GoogleFrNewsRequestError("google blocked")

        connector = GoogleFrNewsConnector(
            client=GoogleFrNewsClient(
                opener=failing_opener,
                requests_per_second=1000,
            )
        )

        with self.assertRaises(GoogleFrNewsRequestError):
            connector.collect(self.request(("MC",), {"MC": "fr"}))

        self.assertEqual(len(connector.last_errors), 1)
        self.assertEqual(connector.last_errors[0][0], "MC")

    def test_registry_registers_google_fr_without_secret_field(self) -> None:
        registry = create_default_registry()

        self.assertIsNotNone(registry.factory_for("google_news_fr"))
        self.assertEqual(registry.secret_fields_for("google_news_fr"), ())


class MarketFrTests(unittest.TestCase):
    def test_market_fr_is_declared(self) -> None:
        self.assertEqual(MARKET_FR, "fr")
        self.assertIn("fr", ALLOWED_MARKETS)

    def test_finnhub_never_queries_fr(self) -> None:
        class ExplodingClient:
            def get_json(self, *args, **kwargs):
                raise AssertionError("FR must not trigger Finnhub requests")

        connector = FinnhubNewsConnector(client=ExplodingClient())

        items = connector.collect(
            CollectionRequest(
                tickers=("MC",),
                start_date=date(2026, 8, 1),
                end_date=date(2026, 8, 2),
                markets={"MC": "fr"},
            )
        )

        self.assertEqual(items, [])
        self.assertEqual(connector.last_errors, ())


if __name__ == "__main__":
    unittest.main()
