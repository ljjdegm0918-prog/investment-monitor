from datetime import date, datetime, timezone
from pathlib import Path
import unittest

from investment_monitor import (
    CollectionRequest,
    YahooBeNewsConnector,
    YahooBeNewsDataError,
    YahooBeNewsRequestError,
)
from investment_monitor.registry import create_default_registry


FIXTURES = Path(__file__).parent / "fixtures" / "be_news"


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
    def __init__(self, fr: bytes, en: bytes) -> None:
        self.fr = fr
        self.en = en
        self.requested: list = []

    def __call__(self, request, timeout=None):
        url = request.full_url
        self.requested.append(url)
        body = self.fr if "lang=fr-BE" in url else self.en
        return FakeResponse(body)


class YahooBeClientTests(unittest.TestCase):
    def test_parses_rss_and_filters_dates(self) -> None:
        from investment_monitor.sources.be_news.yahoo.client import (
            YahooBeNewsClient,
            _parse_rss,
        )

        body = (FIXTURES / "yahoo_be_abi.xml").read_bytes()
        records = _parse_rss(
            body,
            start_date=date(2026, 8, 1),
            end_date=date(2026, 8, 8),
        )

        self.assertEqual(len(records), 3)
        first = records[0]
        self.assertEqual(first["external_id"], "110000301")
        self.assertEqual(
            first["title"],
            "Beer Dynasty Families Sell EUR 731 Million Stake in AB InBev",
        )
        self.assertEqual(
            first["published"],
            datetime(2026, 8, 5, 7, 47, 3, tzinfo=timezone.utc),
        )

        opener = FakeOpener(body, b"")
        client = YahooBeNewsClient(
            opener=opener,
            requests_per_second=1000,
        )
        fetched = client.fetch_news(
            "ABI.BR",
            date(2026, 8, 1),
            date(2026, 8, 8),
        )
        self.assertEqual(len(fetched), 3)
        self.assertIn("s=ABI.BR", opener.requested[0])
        self.assertIn("region=BE", opener.requested[0])
        self.assertIn("lang=fr-BE", opener.requested[0])

    def test_empty_channel_returns_empty_list(self) -> None:
        from investment_monitor.sources.be_news.yahoo.client import _parse_rss

        body = b'<?xml version="1.0"?><rss version="2.0"><channel><title>x</title></channel></rss>'
        records = _parse_rss(
            body,
            start_date=date(2026, 8, 1),
            end_date=date(2026, 8, 8),
        )

        self.assertEqual(records, [])

    def test_malformed_feed_raises_data_error(self) -> None:
        from investment_monitor.sources.be_news.yahoo.client import _parse_rss

        with self.assertRaises(YahooBeNewsDataError):
            _parse_rss(
                b"<html><body>blocked</body></html>",
                start_date=date(2026, 8, 1),
                end_date=date(2026, 8, 8),
            )


class YahooBeSymbolTests(unittest.TestCase):
    def test_symbol_appends_br_suffix(self) -> None:
        from investment_monitor.sources.be_news.symbols import be_yahoo_symbol

        self.assertEqual(be_yahoo_symbol("ABI"), "ABI.BR")
        self.assertEqual(be_yahoo_symbol("kbc"), "KBC.BR")


class YahooBeConnectorTests(unittest.TestCase):
    def request(self, tickers, markets):
        return CollectionRequest(
            tickers=tickers,
            start_date=date(2026, 8, 1),
            end_date=date(2026, 8, 8),
            markets=markets,
        )

    def make_connector(self, symbol_for=None):
        from investment_monitor.sources.be_news.yahoo.client import (
            YahooBeNewsClient,
        )

        opener = FakeOpener(
            (FIXTURES / "yahoo_be_abi.xml").read_bytes(),
            (FIXTURES / "yahoo_be_abi_en.xml").read_bytes(),
        )
        connector = YahooBeNewsConnector(
            client=YahooBeNewsClient(
                opener=opener,
                requests_per_second=1000,
            ),
            symbol_for=symbol_for,
        )
        return connector, opener

    def test_non_be_markets_are_skipped_with_zero_http(self) -> None:
        connector, opener = self.make_connector()

        items = connector.collect(
            self.request(("AAPL", "VOD"), {"AAPL": "us", "VOD": "uk"})
        )

        self.assertEqual(items, [])
        self.assertEqual(connector.last_errors, ())
        self.assertEqual(opener.requested, [])

    def test_be_maps_news_with_canonical_ticker_and_honest_langs(self) -> None:
        connector, opener = self.make_connector()

        items = connector.collect(
            self.request(("ABI.BR",), {"ABI.BR": "be"})
        )

        by_id = {item.external_id: item for item in items}
        self.assertIn("110000301", by_id)
        merged = by_id["110000301"]
        self.assertEqual(merged.source, "yahoo_be")
        self.assertEqual(merged.source_type, "news")
        self.assertEqual(merged.tickers, ("ABI",))
        self.assertEqual(merged.market, "be")
        # Identical titles across the fr-BE and en-US feeds never fake
        # bilingual coverage (live recon 2026-08-10: both feeds are the
        # same English item set), so the merged item stays single-language.
        self.assertEqual(merged.raw_metadata["langs"], "en")
        self.assertEqual(
            merged.title,
            "Beer Dynasty Families Sell EUR 731 Million Stake in AB InBev",
        )
        fr_only = by_id["110000302"]
        self.assertEqual(fr_only.raw_metadata["langs"], "fr")
        self.assertEqual(
            fr_only.raw_metadata["title_fr"],
            "AB InBev publie des résultats record au deuxième trimestre",
        )
        en_only = by_id["110000304"]
        self.assertEqual(en_only.raw_metadata["langs"], "en")
        dual = by_id["110000305"]
        self.assertEqual(dual.raw_metadata["langs"], "en+fr")
        self.assertEqual(dual.title, "AB InBev launches share buyback")
        self.assertEqual(
            dual.raw_metadata["title_fr"],
            "AB InBev lance un rachat d'actions",
        )
        self.assertIn("s=ABI.BR", opener.requested[0])
        self.assertIn("region=BE", opener.requested[0])
        self.assertIn("lang=fr-BE", opener.requested[0])
        self.assertIn("lang=en-US", opener.requested[1])

    def test_symbol_for_injection_is_used(self) -> None:
        connector, opener = self.make_connector(
            symbol_for=lambda code: f"{code}.TEST"
        )

        connector.collect(self.request(("ABI",), {"ABI": "be"}))

        self.assertIn("s=ABI.TEST", opener.requested[0])

    def test_single_ticker_failure_raises_and_records_error(self) -> None:
        from investment_monitor.sources.be_news.yahoo.client import (
            YahooBeNewsClient,
        )

        def failing_opener(request, timeout=None):
            raise YahooBeNewsRequestError("yahoo blocked")

        connector = YahooBeNewsConnector(
            client=YahooBeNewsClient(
                opener=failing_opener,
                requests_per_second=1000,
            )
        )

        with self.assertRaises(YahooBeNewsRequestError):
            connector.collect(self.request(("ABI",), {"ABI": "be"}))

        self.assertEqual(len(connector.last_errors), 1)
        self.assertEqual(connector.last_errors[0][0], "ABI")

    def test_registry_registers_yahoo_be_without_secret_field(self) -> None:
        registry = create_default_registry()

        self.assertIsNotNone(registry.factory_for("yahoo_be"))
        self.assertEqual(registry.secret_fields_for("yahoo_be"), ())


if __name__ == "__main__":
    unittest.main()