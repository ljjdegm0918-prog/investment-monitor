import base64
import json
import os
import unittest
from unittest.mock import patch
from urllib.error import HTTPError

from investment_monitor import (
    CompaniesHouseClient,
    CompaniesHouseDataError,
    CompaniesHouseRequestError,
    ConnectorUnavailableError,
)


class FakeResponse:
    def __init__(self, payload) -> None:
        self._body = json.dumps(payload).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return None

    def read(self) -> bytes:
        return self._body


class FakeOpener:
    def __init__(self, responses=None, errors=None) -> None:
        self.responses = dict(responses or {})
        self.errors = dict(errors or {})
        self.requested: list = []

    def __call__(self, request, timeout=None):
        url = request.full_url
        self.requested.append(request)
        if url in self.errors:
            raise self.errors[url]
        if url in self.responses:
            return FakeResponse(self.responses[url])
        raise HTTPError(url, 404, "not found", {}, None)


COMPANY_URL = (
    "https://api.company-information.service.gov.uk/company/00102498"
)


class CompaniesHouseClientTests(unittest.TestCase):
    def make_client(self, opener, **kwargs) -> CompaniesHouseClient:
        return CompaniesHouseClient(
            api_key="test-ch-key",
            opener=opener,
            requests_per_second=1000,
            **kwargs,
        )

    def test_missing_key_is_reported_as_unavailable(self) -> None:
        with patch.dict(
            os.environ,
            {"COMPANIES_HOUSE_API_KEY": ""},
            clear=False,
        ):
            with self.assertRaises(ConnectorUnavailableError):
                CompaniesHouseClient.from_environment()

    def test_get_company_sends_basic_auth_and_parses_profile(self) -> None:
        opener = FakeOpener(
            responses={
                COMPANY_URL: {
                    "company_name": "BP P.L.C.",
                    "company_number": "00102498",
                }
            }
        )
        client = self.make_client(opener)

        profile = client.get_company("00102498")

        self.assertEqual(profile["company_name"], "BP P.L.C.")
        request = opener.requested[0]
        expected = "Basic " + base64.b64encode(b"test-ch-key:").decode()
        self.assertEqual(request.get_header("Authorization"), expected)

    def test_get_filing_history_returns_items(self) -> None:
        history_url = (
            "https://api.company-information.service.gov.uk/company/"
            "00102498/filing-history?items_per_page=100&start_index=0"
        )
        opener = FakeOpener(
            responses={
                history_url: {
                    "items": [
                        {
                            "transaction_id": "MzA1Mjc1NTk2OWFkaXF6a2N4",
                            "description": "Appointment of a director",
                            "date": "2026-08-01",
                            "type": "AP01",
                        }
                    ]
                }
            }
        )
        client = self.make_client(opener)

        items = client.get_filing_history("00102498")

        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["transaction_id"], "MzA1Mjc1NTk2OWFkaXF6a2N4")

    def test_invalid_filing_history_payload_raises_data_error(self) -> None:
        history_url = (
            "https://api.company-information.service.gov.uk/company/"
            "00102498/filing-history?items_per_page=100&start_index=0"
        )
        opener = FakeOpener(responses={history_url: {"items": {}}})
        client = self.make_client(opener)

        with self.assertRaises(CompaniesHouseDataError):
            client.get_filing_history("00102498")

    def test_http_error_message_does_not_leak_key_or_auth(self) -> None:
        opener = FakeOpener(
            errors={
                COMPANY_URL: HTTPError(
                    COMPANY_URL,
                    401,
                    "unauthorized",
                    {},
                    None,
                )
            }
        )
        client = self.make_client(opener)

        with self.assertRaises(CompaniesHouseRequestError) as raised:
            client.get_company("00102498")

        message = str(raised.exception)
        self.assertNotIn("test-ch-key", message)
        self.assertNotIn("Basic ", message)
        self.assertIn("HTTP 401", message)
        self.assertEqual(raised.exception.status_code, 401)

    def test_retries_429_with_retry_after(self) -> None:
        calls = []

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
            calls.append(request.full_url)
            if len(calls) == 1:
                raise HTTPError(
                    request.full_url,
                    429,
                    "rate limited",
                    {"Retry-After": "2"},
                    None,
                )
            return FakeResponse({"company_name": "BP P.L.C."})

        client = CompaniesHouseClient(
            api_key="test-ch-key",
            opener=opener,
            clock=fake_time.clock,
            sleeper=fake_time.sleep,
            max_retries=1,
            requests_per_second=1000,
        )

        profile = client.get_company("00102498")

        self.assertEqual(len(calls), 2)
        self.assertGreaterEqual(fake_time.sleeps[0], 2.0)
        self.assertEqual(profile["company_name"], "BP P.L.C.")

    def test_redact_secrets_removes_authorization_header(self) -> None:
        from investment_monitor.sources.companies_house.client import (
            redact_secrets,
        )

        text = "Authorization: Basic c2VjcmV0OnBhc3M= token=abc"
        redacted = redact_secrets(text)

        self.assertNotIn("c2VjcmV0", redacted)
        self.assertIn("Authorization: Basic REDACTED", redacted)


class CompaniesHouseFilingHistoryPaginationTests(unittest.TestCase):
    HISTORY_BASE = (
        "https://api.company-information.service.gov.uk/company/"
        "00102498/filing-history?items_per_page=100&start_index="
    )

    def make_client(self, opener, **kwargs) -> CompaniesHouseClient:
        return CompaniesHouseClient(
            api_key="test-ch-key",
            opener=opener,
            requests_per_second=1000,
            **kwargs,
        )

    def page(self, start_index: int, count: int, prefix: str = "txn"):
        return {
            "items": [
                {
                    "transaction_id": f"{prefix}-{start_index + i}",
                    "description": f"filing {start_index + i}",
                    "date": "2026-08-01",
                    "type": "AP01",
                }
                for i in range(count)
            ]
        }

    def requested_indexes(self, opener) -> list:
        indexes = []
        for request in opener.requested:
            url = request.full_url
            indexes.append(int(url.split("start_index=")[1]))
        return indexes

    def test_paginates_until_short_page(self) -> None:
        opener = FakeOpener(
            responses={
                self.HISTORY_BASE + "0": self.page(0, 100),
                self.HISTORY_BASE + "100": self.page(100, 100),
                self.HISTORY_BASE + "200": self.page(200, 50),
            }
        )
        client = self.make_client(opener)

        items = client.get_filing_history("00102498")

        self.assertEqual(len(items), 250)
        self.assertEqual(
            self.requested_indexes(opener),
            [0, 100, 200],
        )

    def test_cap_stops_at_1000_without_next_page(self) -> None:
        opener = FakeOpener(
            responses={
                self.HISTORY_BASE + str(index): self.page(index, 100)
                for index in range(0, 1100, 100)
            }
        )
        client = self.make_client(opener)

        with self.assertLogs(
            "investment_monitor.sources.companies_house.client",
            level="WARNING",
        ) as captured:
            items = client.get_filing_history("00102498")

        self.assertEqual(len(items), 1000)
        self.assertEqual(
            self.requested_indexes(opener),
            list(range(0, 1000, 100)),
        )
        self.assertTrue(
            any("capped at 1000" in line for line in captured.output)
        )

    def test_empty_first_page_returns_empty(self) -> None:
        opener = FakeOpener(
            responses={self.HISTORY_BASE + "0": {"items": []}}
        )
        client = self.make_client(opener)

        items = client.get_filing_history("00102498")

        self.assertEqual(items, [])
        self.assertEqual(self.requested_indexes(opener), [0])

    def test_cross_page_duplicates_kept_once(self) -> None:
        opener = FakeOpener(
            responses={
                self.HISTORY_BASE + "0": self.page(0, 100, prefix="dup"),
                self.HISTORY_BASE + "100": self.page(50, 100, prefix="dup"),
                self.HISTORY_BASE + "200": self.page(200, 50, prefix="dup"),
            }
        )
        client = self.make_client(opener)

        items = client.get_filing_history("00102498")

        self.assertEqual(len(items), 200)
        self.assertEqual(
            [item["transaction_id"] for item in items[:51]],
            [f"dup-{i}" for i in range(51)],
        )
        self.assertEqual(self.requested_indexes(opener), [0, 100, 200])


if __name__ == "__main__":
    unittest.main()
