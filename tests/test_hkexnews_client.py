from datetime import date, datetime, timezone
from pathlib import Path
import unittest

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
        for marker, payload in self.fixtures.items():
            if marker in url:
                return FakeResponse(payload)
        raise AssertionError(f"unexpected url: {url}")


def opener_for(*markers: str) -> FakeOpener:
    url_markers = {
        "activestock_e": "activestock_sehk_e.json",
        "activestock_c": "activestock_sehk_c.json",
        "titlesearch_en": "titleSearchServlet.do",
        "titlesearch_zh": "titleSearchServlet.do",
        "titlesearch_empty": "titleSearchServlet.do",
    }
    fixtures = {}
    for marker in markers:
        fixtures[url_markers[marker]] = (
            FIXTURES / f"{marker}.json"
        ).read_bytes()
    return FakeOpener(fixtures)


def make_client(opener: FakeOpener) -> HkexNewsClient:
    return HkexNewsClient(
        opener=opener,
        clock=lambda: 0.0,
        sleeper=lambda _: None,
        requests_per_second=1000.0,
    )


class HkexNewsClientTests(unittest.TestCase):
    def test_stock_id_for_normalizes_hk_ticker_variants(self) -> None:
        opener = opener_for("activestock_e")
        client = make_client(opener)

        self.assertEqual(client.stock_id_for("00700"), "15157")
        self.assertEqual(client.stock_id_for("700"), "15157")
        self.assertEqual(client.stock_id_for("0700.HK"), "15157")
        self.assertEqual(client.stock_id_for("00001"), "3749")

    def test_stock_id_for_unknown_code_returns_none(self) -> None:
        client = make_client(opener_for("activestock_e"))

        self.assertIsNone(client.stock_id_for("99999"))

    def test_stock_for_returns_name_and_id(self) -> None:
        client = make_client(opener_for("activestock_e"))

        stock = client.stock_for("00700")

        self.assertEqual(stock["stock_id"], "15157")
        self.assertEqual(stock["stock_name"], "TENCENT")
        self.assertEqual(stock["stock_code"], "00700")

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
            {"titleSearchServlet.do": json.dumps(envelope).encode("utf-8")}
        )
        client = make_client(opener)

        records = client.search_disclosures("15157", date(2026, 3, 1), date(2026, 3, 31))

        self.assertEqual(len(records), 2)
        self.assertEqual(records[0]["news_id"], "20260303001234")

    def test_invalid_response_raises_data_error_without_dumping_html(self) -> None:
        opener = FakeOpener(
            {"titleSearchServlet.do": b"<html><body>error page</body></html>"}
        )
        client = make_client(opener)

        with self.assertRaises(HkexNewsDataError) as raised:
            client.search_disclosures("15157", date(2026, 3, 1), date(2026, 3, 31))

        self.assertNotIn("<html>", str(raised.exception))


if __name__ == "__main__":
    unittest.main()
