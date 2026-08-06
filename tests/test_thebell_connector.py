from datetime import date, datetime, timezone
from pathlib import Path
import unittest

from investment_monitor import (
    CollectionRequest,
    TheBellConnector,
    TheBellDataError,
    TheBellRequestError,
)


FIXTURES = Path(__file__).parent / "fixtures" / "kr_news"


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
        self.requested.append(request.full_url)
        return FakeResponse(self.body)


def fixture_bytes(name: str) -> bytes:
    text = (FIXTURES / name).read_text(encoding="utf-8")
    return text.encode("euc-kr")


class TheBellClientTests(unittest.TestCase):
    def test_parses_rows_and_filters_dates(self) -> None:
        from investment_monitor.sources.kr_news.thebell.client import (
            TheBellClient,
            _parse_article_html,
        )

        html = fixture_bytes("thebell_list.html").decode("euc-kr")
        records = _parse_article_html(
            html,
            base_url="http://www.thebell.co.kr",
            start_date=date(2026, 8, 1),
            end_date=date(2026, 8, 5),
        )

        self.assertEqual(len(records), 2)
        self.assertEqual(records[0]["external_id"], "comp:12345")
        self.assertEqual(records[0]["title"], "삼성전자 더벨 기사")
        self.assertEqual(
            records[0]["published"],
            datetime(2026, 8, 4, 15, 0, tzinfo=timezone.utc),
        )
        self.assertIn("comp_id=12345", records[0]["url"])

        opener = FakeOpener(fixture_bytes("thebell_list.html"))
        client = TheBellClient(opener=opener, requests_per_second=1000)
        fetched = client.fetch_news(
            "005930",
            date(2026, 8, 1),
            date(2026, 8, 5),
        )
        self.assertEqual(len(fetched), 2)
        self.assertIn("005930", opener.requested[0])

    def test_missing_article_list_raises_data_error(self) -> None:
        from investment_monitor.sources.kr_news.thebell.client import (
            _parse_article_html,
        )

        with self.assertRaises(TheBellDataError):
            _parse_article_html(
                "<html><body>404 error page</body></html>",
                base_url="http://www.thebell.co.kr",
                start_date=date(2026, 8, 1),
                end_date=date(2026, 8, 5),
            )


class TheBellConnectorTests(unittest.TestCase):
    def request(self, tickers, markets):
        return CollectionRequest(
            tickers=tickers,
            start_date=date(2026, 8, 1),
            end_date=date(2026, 8, 5),
            markets=markets,
        )

    def test_non_kr_markets_are_skipped_with_zero_http(self) -> None:
        from investment_monitor.sources.kr_news.thebell.client import (
            TheBellClient,
        )

        opener = FakeOpener(fixture_bytes("thebell_list.html"))
        connector = TheBellConnector(
            client=TheBellClient(opener=opener, requests_per_second=1000)
        )
        items = connector.collect(
            self.request(("0700",), {"0700": "hk"})
        )

        self.assertEqual(items, [])
        self.assertEqual(opener.requested, [])

    def test_kr_maps_items(self) -> None:
        from investment_monitor.sources.kr_news.thebell.client import (
            TheBellClient,
        )

        opener = FakeOpener(fixture_bytes("thebell_list.html"))
        connector = TheBellConnector(
            client=TheBellClient(opener=opener, requests_per_second=1000)
        )

        items = connector.collect(
            self.request(("005930",), {"005930": "kr"})
        )

        self.assertEqual(len(items), 2)
        first = items[0]
        self.assertEqual(first.source, "thebell")
        self.assertEqual(first.source_type, "news")
        self.assertEqual(first.external_id, "comp:12345")
        self.assertEqual(first.tickers, ("005930",))
        self.assertEqual(first.market, "kr")
        self.assertEqual(first.raw_metadata["comp_id"], "12345")

    def test_failure_is_recorded(self) -> None:
        from investment_monitor.sources.kr_news.thebell.client import (
            TheBellClient,
        )

        def failing_opener(request, timeout=None):
            raise TheBellRequestError("thebell blocked")

        connector = TheBellConnector(
            client=TheBellClient(opener=failing_opener, requests_per_second=1000)
        )
        with self.assertRaises(TheBellRequestError):
            connector.collect(
                self.request(("005930",), {"005930": "kr"})
            )
        self.assertEqual(len(connector.last_errors), 1)


if __name__ == "__main__":
    unittest.main()
