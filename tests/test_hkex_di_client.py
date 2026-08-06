from datetime import date, datetime, timezone
from pathlib import Path
import unittest
from urllib.parse import parse_qs, urlparse

from investment_monitor import (
    HkexDiClient,
    HkexDiDataError,
    HkexDiRequestError,
)


FIXTURES = Path(__file__).parent / "fixtures" / "hkex_di"


def fixture_bytes(name: str) -> bytes:
    return (FIXTURES / name).read_bytes()


class FakeResponse:
    def __init__(self, payload: bytes, final_url: str = "") -> None:
        self._body = payload
        self._url = final_url

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return None

    def read(self) -> bytes:
        return self._body

    def geturl(self) -> str:
        return self._url


class FakeOpener:
    def __init__(self, sequence) -> None:
        self.sequence = list(sequence)
        self.requested: list = []

    def __call__(self, request, timeout=None):
        parsed = urlparse(request.full_url)
        form = parse_qs(request.data.decode("utf-8")) if request.data else {}
        self.requested.append((parsed.path, form))
        if not self.sequence:
            raise AssertionError("unexpected extra request")
        final_url, body = self.sequence.pop(0)
        return FakeResponse(body, final_url)


class HkexDiClientTests(unittest.TestCase):
    def make_client(self, opener, **kwargs) -> HkexDiClient:
        return HkexDiClient(
            opener=opener,
            requests_per_second=1000,
            **kwargs,
        )

    def test_search_disclosures_posts_form_and_parses_notice_rows(self) -> None:
        opener = FakeOpener(
            [
                ("", fixture_bytes("search_form.html")),
                (
                    "https://di.hkex.com.hk/filing/di/NSSrchCorpList.aspx",
                    fixture_bytes("notices_grid.html"),
                ),
            ]
        )
        client = self.make_client(opener)

        records = client.search_disclosures(
            "00700",
            date(2016, 10, 3),
            date(2016, 10, 4),
        )

        self.assertEqual(len(records), 2)
        first = records[0]
        self.assertEqual(first["serial"], "20161003000123")
        self.assertEqual(
            first["published_at"],
            datetime(2016, 10, 3, 4, 0, tzinfo=timezone.utc),
        )
        self.assertEqual(first["person"], "MA HUA TENG")
        self.assertEqual(first["reason"], "Acquisition of shares")
        self.assertEqual(
            first["url"],
            "https://di.hkex.com.hk/filing/di/"
            "NSSrchNotice.aspx?serial=20161003000123",
        )

        paths = [path for path, _ in opener.requested]
        self.assertEqual(
            paths,
            [
                "/filing/di/NSSrchCorp.aspx",
                "/filing/di/NSSrchCorp.aspx",
            ],
        )
        form = opener.requested[1][1]
        self.assertEqual(form["txtStockCode"], ["00700"])
        self.assertEqual(form["ddlStartDateDD"], ["03"])
        self.assertEqual(form["ddlStartDateMM"], ["10"])
        self.assertEqual(form["ddlStartDateYYYY"], ["2016"])
        self.assertEqual(form["ddlEndDateDD"], ["04"])
        self.assertEqual(form["cmdSearch"], ["Search"])
        self.assertEqual(form["__VIEWSTATE"], ["AAABBBCCC"])

    def test_out_of_archive_window_skips_silently(self) -> None:
        opener = FakeOpener([])
        client = self.make_client(opener)

        records = client.search_disclosures(
            "00700",
            date(2026, 8, 1),
            date(2026, 8, 6),
        )

        self.assertEqual(records, [])
        self.assertEqual(opener.requested, [])

    def test_summary_only_page_raises_data_error_not_fake_success(self) -> None:
        opener = FakeOpener(
            [
                ("", fixture_bytes("search_form.html")),
                ("", fixture_bytes("report_summary_list.html")),
            ]
        )
        client = self.make_client(opener)

        with self.assertRaisesRegex(HkexDiDataError, "report-type"):
            client.search_disclosures(
                "00700",
                date(2016, 10, 3),
                date(2016, 10, 4),
            )

    def test_empty_list_returns_empty_records(self) -> None:
        opener = FakeOpener(
            [
                ("", fixture_bytes("search_form.html")),
                ("", fixture_bytes("empty_list.html")),
            ]
        )
        client = self.make_client(opener)

        records = client.search_disclosures(
            "00700",
            date(2016, 10, 3),
            date(2016, 10, 4),
        )

        self.assertEqual(records, [])

    def test_request_failure_raises_request_error(self) -> None:
        from urllib.error import URLError

        def failing_opener(request, timeout=None):
            raise URLError("blocked")

        client = self.make_client(failing_opener)

        with self.assertRaises(HkexDiRequestError):
            client._get("https://di.hkex.com.hk/filing/di/NSSrchCorp.aspx")


if __name__ == "__main__":
    unittest.main()
