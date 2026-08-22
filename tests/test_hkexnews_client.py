from datetime import date, datetime, timezone
from pathlib import Path
import unittest
from urllib.parse import parse_qs, urlsplit

from investment_monitor.sources.hkexnews.client import (
    HkexNewsClient,
    HkexNewsDataError,
)


FIXTURES = Path(__file__).parent / "fixtures" / "hkexnews"


class FakeResponse:
    def __init__(self, payload: bytes) -> None:
        self._payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self) -> bytes:
        return self._payload


class FakeOpener:
    def __init__(self, fixtures) -> None:
        self.fixtures = dict(fixtures)
        self.calls: list = []

    def __call__(self, request, timeout=None):
        url = request.full_url if hasattr(request, "full_url") else str(request)
        self.calls.append(url)
        path = urlsplit(url).path
        for marker, payload in self.fixtures.items():
            if path == marker:
                return FakeResponse(payload)
        raise AssertionError(f"unexpected url: {url}")


def opener_for(*markers: str) -> FakeOpener:
    url_markers = {
        "activestock_e": "/ncms/script/eds/activestock_sehk_e.json",
        "activestock_c": "/ncms/script/eds/activestock_sehk_c.json",
        "inactivestock_e": "/ncms/script/eds/inactivestock_sehk_e.json",
        "inactivestock_c": "/ncms/script/eds/inactivestock_sehk_c.json",
        "titlesearch_en": "/search/titleSearchServlet.do",
        "titlesearch_zh": "/search/titleSearchServlet.do",
        "titlesearch_empty": "/search/titleSearchServlet.do",
    }
    file_names = {
        "activestock_e": "activestock_e.json",
        "activestock_c": "activestock_c.json",
        "inactivestock_e": "inactivestock_sehk_e.json",
        "inactivestock_c": "inactivestock_sehk_c.json",
        "titlesearch_en": "titlesearch_en.json",
        "titlesearch_zh": "titlesearch_zh.json",
        "titlesearch_empty": "titlesearch_empty.json",
    }
    fixtures = {}
    for marker in markers:
        fixtures[url_markers[marker]] = (
            FIXTURES / file_names[marker]
        ).read_bytes()
    return FakeOpener(fixtures)


def make_client(opener: FakeOpener) -> HkexNewsClient:
    return HkexNewsClient(
        opener=opener,
        clock=lambda: 0.0,
        sleeper=lambda _: None,
        requests_per_second=1000.0,
    )


def search_envelope(
    rows,
    *,
    loaded_record,
    record_count,
    has_next_row,
    row_range,
    lang="E",
) -> bytes:
    import json

    return json.dumps(
        {
            "result": json.dumps(rows),
            "hasNextRow": has_next_row,
            "rowRange": row_range,
            "lang": lang,
            "loadedRecord": loaded_record,
            "recordCnt": record_count,
        }
    ).encode("utf-8")


def raw_row(news_id: str) -> dict:
    return {
        "NEWS_ID": news_id,
        "TITLE": f"Announcement {news_id}",
        "DATE_TIME": "2026-03-03 16:40:00",
        "FILE_LINK": f"/listedco/listconews/sehk/2026/0303/{news_id}.htm",
        "STOCK_CODE": "00700",
        "STOCK_NAME": "TENCENT",
        "FILE_TYPE": "Announcements and Notices",
    }


class SequencedSearchOpener:
    def __init__(self, pages: list[bytes]) -> None:
        self.pages = list(pages)
        self.calls: list[str] = []

    def __call__(self, request, timeout=None):
        url = request.full_url if hasattr(request, "full_url") else str(request)
        self.calls.append(url)
        if urlsplit(url).path != "/search/titleSearchServlet.do":
            raise AssertionError(f"unexpected url: {url}")
        if not self.pages:
            raise AssertionError("too many Title Search requests")
        return FakeResponse(self.pages.pop(0))


class HkexNewsClientTests(unittest.TestCase):
    def test_stock_id_for_normalizes_hk_ticker_variants(self) -> None:
        opener = opener_for("activestock_e", "inactivestock_e")
        client = make_client(opener)

        self.assertEqual(client.stock_id_for("00700"), "15157")
        self.assertEqual(client.stock_id_for("700"), "15157")
        self.assertEqual(client.stock_id_for("0700.HK"), "15157")
        self.assertEqual(client.stock_id_for("00001"), "3749")

    def test_stock_id_for_unknown_code_returns_none(self) -> None:
        client = make_client(opener_for("activestock_e", "inactivestock_e"))

        self.assertIsNone(client.stock_id_for("99999"))

    def test_stock_for_returns_name_and_id(self) -> None:
        client = make_client(opener_for("activestock_e", "inactivestock_e"))

        stock = client.stock_for("00700")

        self.assertEqual(stock["stock_id"], "15157")
        self.assertEqual(stock["stock_name"], "TENCENT")
        self.assertEqual(stock["stock_code"], "00700")

    def test_fetch_stock_list_parses_active_and_inactive_lists(self) -> None:
        opener = opener_for(
            "activestock_e",
            "activestock_c",
            "inactivestock_e",
            "inactivestock_c",
        )
        client = make_client(opener)

        active = client.fetch_stock_list("active", "e")
        active_zh = client.fetch_stock_list("active", "c")
        inactive = client.fetch_stock_list("inactive", "e")
        inactive_zh = client.fetch_stock_list("inactive", "c")

        self.assertEqual(
            active[0],
            {
                "stock_code": "00001",
                "stock_id": "3749",
                "stock_name": "CKH HOLDINGS",
            },
        )
        self.assertEqual(active_zh[1]["stock_name"], "騰訊控股")
        self.assertEqual(inactive[0]["stock_code"], "00010")
        self.assertEqual(inactive_zh[0]["stock_name"], "恒生銀行")

    def test_stock_id_for_inactive_security_is_available_for_history(self) -> None:
        client = make_client(opener_for("activestock_e", "inactivestock_e"))

        self.assertEqual(client.stock_id_for("00010"), "3756")

    def test_fetch_stock_list_rejects_unknown_status_or_lang(self) -> None:
        client = make_client(opener_for("activestock_e"))

        with self.assertRaises(ValueError):
            client.fetch_stock_list("bogus", "e")
        with self.assertRaises(ValueError):
            client.fetch_stock_list("active", "x")

    def test_search_disclosures_parses_rows_into_utc_records(self) -> None:
        opener = opener_for("titlesearch_en")
        client = make_client(opener)

        records = client.search_disclosures(
            "15157",
            date(2026, 3, 1),
            date(2026, 3, 31),
            lang="E",
        )

        self.assertEqual(len(records), 2)
        first = records[0]
        self.assertEqual(first["news_id"], "20260303001234")
        self.assertEqual(first["title"], "Board Meeting Date")
        self.assertEqual(
            first["published_at"],
            datetime(2026, 3, 3, 8, 40, tzinfo=timezone.utc),
        )
        self.assertEqual(
            first["url"],
            "https://www1.hkexnews.hk"
            "/listedco/listconews/sehk/2026/0303/20260303001234.htm",
        )
        self.assertEqual(first["stock_code"], "00700")
        self.assertEqual(first["file_type"], "Announcements and Notices")
        self.assertEqual(records[1]["published_at"], datetime(2026, 3, 3, 10, 5, tzinfo=timezone.utc))

    def test_search_disclosures_empty_result_returns_empty_list(self) -> None:
        client = make_client(opener_for("titlesearch_empty"))

        records = client.search_disclosures(
            "15157",
            date(2026, 3, 1),
            date(2026, 3, 31),
            lang="E",
        )

        self.assertEqual(records, [])

    def test_search_disclosures_accepts_result_as_native_list(self) -> None:
        import json

        envelope = json.loads(
            (FIXTURES / "titlesearch_en.json").read_text(encoding="utf-8")
        )
        envelope["result"] = json.loads(envelope["result"])
        opener = FakeOpener(
            {
                "/search/titleSearchServlet.do": (
                    json.dumps(envelope).encode("utf-8")
                )
            }
        )
        client = make_client(opener)

        records = client.search_disclosures("15157", date(2026, 3, 1), date(2026, 3, 31))

        self.assertEqual(len(records), 2)
        self.assertEqual(records[0]["news_id"], "20260303001234")

    def test_search_disclosures_uses_official_cumulative_load_more_paging(self) -> None:
        first = raw_row("20260303001234")
        second = raw_row("20260303001235")
        opener = SequencedSearchOpener(
            [
                search_envelope(
                    [first],
                    loaded_record=1,
                    record_count=2,
                    has_next_row=True,
                    row_range=100,
                ),
                search_envelope(
                    [first, second],
                    loaded_record=2,
                    record_count=2,
                    has_next_row=False,
                    row_range=200,
                ),
            ]
        )
        client = make_client(opener)

        records = client.search_disclosures(
            "15157", date(2026, 3, 1), date(2026, 3, 31)
        )

        self.assertEqual([record["news_id"] for record in records], [
            "20260303001234",
            "20260303001235",
        ])
        first_query = parse_qs(urlsplit(opener.calls[0]).query)
        second_query = parse_qs(urlsplit(opener.calls[1]).query)
        self.assertEqual(first_query["rowRange"], ["100"])
        self.assertEqual(second_query["rowRange"], ["200"])
        self.assertEqual(first_query["sortDir"], ["0"])
        self.assertEqual(first_query["t1code"], ["-2"])
        self.assertEqual(first_query["fromDate"], ["20260301"])
        self.assertEqual(first_query["toDate"], ["20260331"])

    def test_search_disclosures_chinese_uses_official_c_language_code(self) -> None:
        opener = SequencedSearchOpener(
            [
                search_envelope(
                    [],
                    loaded_record=0,
                    record_count=0,
                    has_next_row=False,
                    row_range=100,
                    lang="C",
                )
            ]
        )
        client = make_client(opener)

        self.assertEqual(
            client.search_disclosures("15157", date(2026, 3, 1), date(2026, 3, 31), lang="zh"),
            [],
        )
        self.assertEqual(parse_qs(urlsplit(opener.calls[0]).query)["lang"], ["C"])

    def test_search_disclosures_rejects_missing_or_contradictory_empty_envelope(self) -> None:
        import json

        for payload in (
            json.dumps({"result": "[]"}).encode("utf-8"),
            search_envelope(
                [],
                loaded_record=0,
                record_count=1,
                has_next_row=False,
                row_range=100,
            ),
        ):
            with self.subTest(payload=payload):
                client = make_client(SequencedSearchOpener([payload]))
                with self.assertRaises(HkexNewsDataError):
                    client.search_disclosures(
                        "15157", date(2026, 3, 1), date(2026, 3, 31)
                    )

    def test_search_disclosures_rejects_stalled_or_malformed_paging(self) -> None:
        first = raw_row("20260303001234")
        stalled = search_envelope(
            [first],
            loaded_record=1,
            record_count=2,
            has_next_row=True,
            row_range=100,
        )
        missing_title = raw_row("20260303001235")
        del missing_title["TITLE"]
        malformed = search_envelope(
            [missing_title],
            loaded_record=1,
            record_count=1,
            has_next_row=False,
            row_range=100,
        )
        for pages in ([stalled, stalled], [malformed]):
            with self.subTest(pages=pages):
                client = make_client(SequencedSearchOpener(pages))
                with self.assertRaises(HkexNewsDataError):
                    client.search_disclosures(
                        "15157", date(2026, 3, 1), date(2026, 3, 31)
                    )

    def test_invalid_response_raises_data_error_without_dumping_html(self) -> None:
        opener = FakeOpener(
            {
                "/search/titleSearchServlet.do": (
                    b"<html><body>error page</body></html>"
                )
            }
        )
        client = make_client(opener)

        with self.assertRaises(HkexNewsDataError) as raised:
            client.search_disclosures("15157", date(2026, 3, 1), date(2026, 3, 31))

        self.assertNotIn("<html>", str(raised.exception))


if __name__ == "__main__":
    unittest.main()
