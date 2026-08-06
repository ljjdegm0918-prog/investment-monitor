from datetime import date, datetime, timezone
from pathlib import Path
import re
import unittest

from investment_monitor import (
    CollectionRequest,
    NaverNewsConnector,
    NaverNewsDataError,
    NaverNewsRequestError,
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


def make_page(rows) -> bytes:
    body = "".join(
        '<tr><td class="title"><a href="/news_read.naver?'
        f'office_id={office_id}&amp;article_id={article_id}">'
        f"{title}</a></td><td class=\"info\">YONHAP</td>"
        f'<td class="date">{date_text}</td></tr>'
        for office_id, article_id, title, date_text in rows
    )
    html = (
        '<html lang="ko"><body><div class="tb_cont _replaceNewsLink">'
        '<table class="type5"><thead><tr><th>title</th><th>source</th>'
        "<th>date</th></tr></thead>"
        f"<tbody>{body}</tbody></table></div></body></html>"
    )
    return html.encode("euc-kr")


class MultiPageOpener:
    def __init__(self, pages) -> None:
        self.pages = pages
        self.requested: list = []

    def __call__(self, request, timeout=None):
        url = request.full_url
        self.requested.append(url)
        page = int(re.search(r"page=(\d+)", url).group(1))
        if page not in self.pages:
            raise AssertionError(f"unexpected page request: {url}")
        return FakeResponse(self.pages[page])


class NaverNewsClientTests(unittest.TestCase):
    def test_parses_rows_and_filters_dates(self) -> None:
        from investment_monitor.sources.kr_news.naver.client import (
            NaverNewsClient,
            _parse_news_html,
        )

        html = fixture_bytes("naver_news.html").decode("euc-kr")
        records = _parse_news_html(
            html,
            start_date=date(2026, 8, 1),
            end_date=date(2026, 8, 5),
        )

        self.assertEqual(len(records), 2)
        self.assertEqual(records[0]["office_id"], "008")
        self.assertEqual(records[0]["article_id"], "0000012345")
        self.assertEqual(records[0]["title"], "삼성전자 배당 확대 결정")
        self.assertEqual(records[0]["provider"], "연합인포맥스")
        self.assertEqual(
            records[0]["published"],
            datetime(2026, 8, 5, 6, 40, tzinfo=timezone.utc),
        )

        opener = FakeOpener(fixture_bytes("naver_news.html"))
        client = NaverNewsClient(opener=opener, requests_per_second=1000)
        fetched = client.fetch_news(
            "005930",
            date(2026, 8, 1),
            date(2026, 8, 5),
        )
        self.assertEqual(len(fetched), 2)
        self.assertIn("code=005930", opener.requested[0])

    def test_empty_message_returns_empty_list(self) -> None:
        from investment_monitor.sources.kr_news.naver.client import (
            _parse_news_html,
        )

        html = fixture_bytes("naver_news_empty.html").decode("euc-kr")
        records = _parse_news_html(
            html,
            start_date=date(2026, 8, 1),
            end_date=date(2026, 8, 5),
        )

        self.assertEqual(records, [])

    def test_missing_table_raises_data_error(self) -> None:
        from investment_monitor.sources.kr_news.naver.client import (
            _parse_news_html,
        )

        with self.assertRaises(NaverNewsDataError):
            _parse_news_html(
                "<html><body>unexpected</body></html>",
                start_date=date(2026, 8, 1),
                end_date=date(2026, 8, 5),
            )


class NaverNewsConnectorTests(unittest.TestCase):
    def request(self, tickers, markets):
        return CollectionRequest(
            tickers=tickers,
            start_date=date(2026, 8, 1),
            end_date=date(2026, 8, 5),
            markets=markets,
        )

    def test_non_kr_markets_are_skipped_with_zero_http(self) -> None:
        opener = FakeOpener(fixture_bytes("naver_news.html"))
        from investment_monitor.sources.kr_news.naver.client import (
            NaverNewsClient,
        )

        connector = NaverNewsConnector(
            client=NaverNewsClient(opener=opener, requests_per_second=1000)
        )
        items = connector.collect(
            self.request(("AAPL", "0700"), {"AAPL": "us", "0700": "hk"})
        )

        self.assertEqual(items, [])
        self.assertEqual(connector.last_errors, ())
        self.assertEqual(opener.requested, [])

    def test_kr_maps_items_and_normalizes_ticker(self) -> None:
        from investment_monitor.sources.kr_news.naver.client import (
            NaverNewsClient,
        )

        opener = FakeOpener(fixture_bytes("naver_news.html"))
        connector = NaverNewsConnector(
            client=NaverNewsClient(opener=opener, requests_per_second=1000)
        )

        items = connector.collect(
            self.request(("5930",), {"5930": "kr"})
        )

        self.assertEqual(len(items), 2)
        first = items[0]
        self.assertEqual(first.source, "naver_news")
        self.assertEqual(first.source_type, "news")
        self.assertEqual(first.external_id, "008:0000012345")
        self.assertEqual(first.tickers, ("005930",))
        self.assertEqual(first.market, "kr")
        self.assertEqual(first.title, "삼성전자 배당 확대 결정")
        self.assertIn("n.news.naver.com/mnews/article/008/0000012345", first.url)
        self.assertEqual(first.raw_metadata["scraped"], True)
        self.assertIn("code=005930", opener.requested[0])

    def test_failure_is_recorded(self) -> None:
        from investment_monitor.sources.kr_news.naver.client import (
            NaverNewsClient,
        )

        def failing_opener(request, timeout=None):
            raise NaverNewsRequestError("naver blocked")

        connector = NaverNewsConnector(
            client=NaverNewsClient(opener=failing_opener, requests_per_second=1000)
        )

        with self.assertRaises(NaverNewsRequestError):
            connector.collect(
                self.request(("005930",), {"005930": "kr"})
            )

        self.assertEqual(len(connector.last_errors), 1)


class NaverNewsPaginationTests(unittest.TestCase):
    def make_client(self, pages, max_pages=10):
        from investment_monitor.sources.kr_news.naver.client import (
            NaverNewsClient,
        )

        return NaverNewsClient(
            opener=MultiPageOpener(pages),
            requests_per_second=1000,
            max_pages=max_pages,
        )

    def test_paginates_until_oldest_before_start_date(self) -> None:
        pages = {
            1: make_page([
                ("008", "100", "News A", "2026.08.05 15:40"),
                ("008", "101", "News B", "2026.08.04 09:00"),
            ]),
            2: make_page([
                ("008", "102", "News C", "2026.08.02 10:00"),
                ("008", "103", "Old", "2026.07.30 09:00"),
            ]),
        }
        client = self.make_client(pages)

        records = client.fetch_news(
            "005930",
            date(2026, 8, 1),
            date(2026, 8, 5),
        )

        self.assertEqual(
            [record["article_id"] for record in records],
            ["100", "101", "102"],
        )
        self.assertEqual(len(client._opener.requested), 2)

    def test_page2_in_window_news_is_not_lost(self) -> None:
        pages = {
            1: make_page([
                ("008", "100", "News A", "2026.08.05 15:40"),
            ]),
            2: make_page([
                ("008", "101", "News D", "2026.08.02 10:00"),
                ("008", "102", "Old", "2026.07.31 09:00"),
            ]),
        }
        client = self.make_client(pages)

        records = client.fetch_news(
            "005930",
            date(2026, 8, 1),
            date(2026, 8, 5),
        )

        self.assertEqual(
            [record["article_id"] for record in records],
            ["100", "101"],
        )

    def test_empty_page_stops_pagination(self) -> None:
        pages = {
            1: make_page([
                ("008", "100", "News A", "2026.08.05 15:40"),
                ("008", "101", "News B", "2026.08.04 09:00"),
            ]),
            2: fixture_bytes("naver_news_empty.html"),
        }
        client = self.make_client(pages)

        records = client.fetch_news(
            "005930",
            date(2026, 8, 1),
            date(2026, 8, 5),
        )

        self.assertEqual(len(records), 2)
        self.assertEqual(len(client._opener.requested), 2)

    def test_max_pages_caps_requests_and_warns(self) -> None:
        pages = {
            1: make_page([("008", "100", "News A", "2026.08.05 15:40")]),
            2: make_page([("008", "101", "News B", "2026.08.04 09:00")]),
        }
        client = self.make_client(pages, max_pages=2)

        with self.assertLogs(
            "investment_monitor.sources.kr_news.naver.client",
            level="WARNING",
        ) as captured:
            records = client.fetch_news(
                "005930",
                date(2026, 8, 1),
                date(2026, 8, 5),
            )

        self.assertEqual(len(records), 2)
        self.assertEqual(len(client._opener.requested), 2)
        self.assertTrue(
            any("max_pages" in line for line in captured.output)
        )

    def test_cross_page_duplicate_kept_once(self) -> None:
        pages = {
            1: make_page([("008", "100", "News A", "2026.08.05 15:40")]),
            2: make_page([
                ("008", "100", "News A again", "2026.08.04 09:00"),
                ("008", "101", "News B", "2026.08.03 09:00"),
            ]),
        }
        client = self.make_client(pages, max_pages=2)

        records = client.fetch_news(
            "005930",
            date(2026, 8, 1),
            date(2026, 8, 5),
        )

        self.assertEqual(
            [record["article_id"] for record in records],
            ["100", "101"],
        )
        self.assertEqual(records[0]["title"], "News A")


if __name__ == "__main__":
    unittest.main()
