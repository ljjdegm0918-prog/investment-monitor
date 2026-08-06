from datetime import date
from pathlib import Path
import unittest
from urllib.error import HTTPError
from urllib.parse import parse_qs, urlparse

from investment_monitor import (
    KindClient,
    KindDataError,
    KindRequestError,
)


FIXTURES = Path(__file__).parent / "fixtures" / "kind"


def fixture_bytes(name: str) -> bytes:
    return (FIXTURES / name).read_bytes()


class FakeResponse:
    def __init__(self, payload: bytes) -> None:
        self._body = payload

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return None

    def read(self) -> bytes:
        return self._body


class FakeOpener:
    def __init__(self, body: bytes, errors=None) -> None:
        self.body = body
        self.errors = errors or {}
        self.requested: list = []

    def __call__(self, request, timeout=None):
        parsed = urlparse(request.full_url)
        form = parse_qs(request.data.decode("utf-8")) if request.data else {}
        self.requested.append((parsed.path, form))
        error = self.errors.get(parsed.path)
        if error is not None:
            raise error
        return FakeResponse(self.body)


class KindClientTests(unittest.TestCase):
    def make_client(self, opener, **kwargs) -> KindClient:
        return KindClient(
            opener=opener,
            requests_per_second=1000,
            **kwargs,
        )

    def test_search_disclosures_posts_form_and_parses_rows(self) -> None:
        opener = FakeOpener(fixture_bytes("disclosures_fragment.html"))
        client = self.make_client(opener)

        records = client.search_disclosures(
            "005930",
            date(2026, 8, 1),
            date(2026, 8, 5),
        )

        self.assertEqual(len(records), 2)
        first = records[0]
        self.assertEqual(first["acpt_no"], "20260805000501")
        self.assertEqual(first["rcept_no"], "20260805000501")
        self.assertEqual(first["title"], "임원ㆍ주요주주특정증권등소유상황보고서")
        self.assertEqual(first["company_name"], "삼성전자")
        self.assertEqual(first["datetime_text"], "2026-08-05 15:40")
        self.assertEqual(first["market"], "유가증권")
        self.assertEqual(first["submitter"], "황상준")
        self.assertEqual(records[1]["acpt_no"], "20260805000291")

        path, form = opener.requested[0]
        self.assertEqual(path, "/disclosure/searchdisclosurebycorp.do")
        self.assertEqual(form["method"], ["searchDisclosureByCorpSub"])
        self.assertEqual(form["repIsuSrtCd"], ["A005930"])
        self.assertEqual(form["allRepIsuSrtCd"], ["A005930"])
        self.assertEqual(form["searchCorpName"], ["005930"])
        self.assertEqual(form["fromDate"], ["2026-08-01"])
        self.assertEqual(form["toDate"], ["2026-08-05"])

    def test_empty_result_returns_empty_list(self) -> None:
        opener = FakeOpener(fixture_bytes("empty_fragment.html"))
        client = self.make_client(opener)

        records = client.search_disclosures(
            "005930",
            date(2026, 8, 1),
            date(2026, 8, 5),
        )

        self.assertEqual(records, [])

    def test_error_page_raises_data_error(self) -> None:
        opener = FakeOpener(fixture_bytes("error_page.html"))
        client = self.make_client(opener)

        with self.assertRaises(KindDataError):
            client.search_disclosures(
                "005930",
                date(2026, 8, 1),
                date(2026, 8, 5),
            )

    def test_missing_table_raises_data_error(self) -> None:
        opener = FakeOpener(b"<html><body>unexpected</body></html>")
        client = self.make_client(opener)

        with self.assertRaises(KindDataError):
            client.search_disclosures(
                "005930",
                date(2026, 8, 1),
                date(2026, 8, 5),
            )

    def test_retries_temporary_http_failure(self) -> None:
        calls = []

        def opener(request, timeout=None):
            calls.append(request.full_url)
            if len(calls) == 1:
                raise HTTPError(
                    request.full_url,
                    429,
                    "rate limited",
                    {},
                    None,
                )
            return FakeResponse(fixture_bytes("empty_fragment.html"))

        client = self.make_client(opener, max_retries=1)
        records = client.search_disclosures(
            "005930",
            date(2026, 8, 1),
            date(2026, 8, 5),
        )

        self.assertEqual(len(calls), 2)
        self.assertEqual(records, [])

    def test_rate_limit_spaces_requests(self) -> None:
        class FakeTime:
            def __init__(self) -> None:
                self.now = 0.0
                self.sleeps = []

            def clock(self) -> float:
                return self.now

            def sleep(self, seconds: float) -> None:
                self.sleeps.append(seconds)
                self.now += seconds

        fake_time = FakeTime()

        def opener(request, timeout=None):
            return FakeResponse(fixture_bytes("empty_fragment.html"))

        client = KindClient(
            opener=opener,
            clock=fake_time.clock,
            sleeper=fake_time.sleep,
            requests_per_second=2.0,
        )
        client.search_disclosures("005930", date(2026, 8, 1), date(2026, 8, 5))
        client.search_disclosures("005930", date(2026, 8, 1), date(2026, 8, 5))

        self.assertGreaterEqual(sum(fake_time.sleeps), 0.49)

    def test_viewer_url_uses_acceptance_number(self) -> None:
        client = self.make_client(FakeOpener(b""))

        url = client.viewer_url("20260805000501")

        self.assertIn("method=searchInitInfo", url)
        self.assertIn("acptNo=20260805000501", url)
        self.assertTrue(url.startswith("https://kind.krx.co.kr/"))


if __name__ == "__main__":
    unittest.main()
