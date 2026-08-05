import json
import os
import unittest
from unittest.mock import patch
from urllib.error import HTTPError

from investment_monitor import (
    ConnectorUnavailableError,
    DartClient,
    DartDataError,
    DartRequestError,
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
        base = url.split("?")[0]
        self.requested.append(url)
        if base in self.errors:
            raise self.errors[base]
        if base in self.responses:
            return FakeResponse(self.responses[base])
        raise HTTPError(url, 404, "not found", {}, None)


LIST_URL = "https://opendart.fss.or.kr/api/list.json"


class DartClientTests(unittest.TestCase):
    def make_client(self, opener, **kwargs) -> DartClient:
        return DartClient(
            api_key="test-key",
            opener=opener,
            requests_per_second=1000,
            **kwargs,
        )

    def test_missing_key_is_reported_as_unavailable(self) -> None:
        with patch.dict(os.environ, {"DART_API_KEY": ""}, clear=False):
            with self.assertRaises(ConnectorUnavailableError):
                DartClient.from_environment()

    def test_get_list_returns_records_on_status_000(self) -> None:
        opener = FakeOpener(
            responses={
                LIST_URL: {
                    "status": "000",
                    "message": "정상",
                    "list": [
                        {
                            "rcept_no": "20260801000001",
                            "report_nm": "사업보고서",
                            "rcept_dt": "20260801",
                        }
                    ],
                }
            }
        )
        client = self.make_client(opener)

        records = client.get_list(
            corp_code="00593000",
            bgn_de="20260801",
            end_de="20260802",
        )

        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["rcept_no"], "20260801000001")
        self.assertIn("corp_code=00593000", opener.requested[0])
        self.assertIn("crtfc_key=test-key", opener.requested[0])

    def test_get_list_returns_empty_on_status_200(self) -> None:
        opener = FakeOpener(
            responses={LIST_URL: {"status": "200", "message": "정상"}}
        )
        client = self.make_client(opener)

        records = client.get_list(
            corp_code="00593000",
            bgn_de="20260801",
            end_de="20260802",
        )

        self.assertEqual(records, [])

    def test_get_list_raises_on_error_status(self) -> None:
        opener = FakeOpener(
            responses={LIST_URL: {"status": "013", "message": "사용할 수 없는 키"}}
        )
        client = self.make_client(opener)

        with self.assertRaises(DartRequestError) as raised:
            client.get_list(
                corp_code="00593000",
                bgn_de="20260801",
                end_de="20260802",
            )

        self.assertIn("013", str(raised.exception))
        self.assertNotIn("test-key", str(raised.exception))

    def test_http_failure_message_is_redacted(self) -> None:
        opener = FakeOpener(
            errors={
                LIST_URL: HTTPError(LIST_URL, 503, "unavailable", {}, None)
            }
        )
        client = self.make_client(opener)

        with self.assertRaises(DartRequestError) as raised:
            client.get_list(
                corp_code="00593000",
                bgn_de="20260801",
                end_de="20260802",
            )

        message = str(raised.exception)
        self.assertNotIn("test-key", message)
        self.assertIn("crtfc_key=REDACTED", message)

    def test_retries_temporary_http_failure(self) -> None:
        calls = []

        def opener(request, timeout=None):
            url = request.full_url.split("?")[0]
            calls.append(url)
            if len(calls) == 1:
                raise HTTPError(url, 429, "rate limited", {}, None)
            return FakeResponse({"status": "000", "list": []})

        client = self.make_client(opener, max_retries=1)

        records = client.get_list(
            corp_code="00593000",
            bgn_de="20260801",
            end_de="20260802",
        )

        self.assertEqual(len(calls), 2)
        self.assertEqual(records, [])

    def test_redact_secrets_removes_crtfc_key_values(self) -> None:
        from investment_monitor.sources.dart.client import _redact_secrets

        text = (
            "https://opendart.fss.or.kr/api/list.json?"
            "corp_code=00593000&crtfc_key=secret-value&x=1"
        )
        redacted = _redact_secrets(text)

        self.assertNotIn("secret-value", redacted)
        self.assertIn("crtfc_key=REDACTED", redacted)

    def test_invalid_json_response_raises_data_error(self) -> None:
        class BrokenResponse:
            def __enter__(self):
                return self

            def __exit__(self, *args):
                return None

            def read(self) -> bytes:
                return b"not json"

        def opener(request, timeout=None):
            return BrokenResponse()

        client = self.make_client(opener)
        with self.assertRaises(DartDataError):
            client.get_list(
                corp_code="00593000",
                bgn_de="20260801",
                end_de="20260802",
            )


if __name__ == "__main__":
    unittest.main()
