"""P0-2 IBKR secdef adapter tests (offline fake opener)."""

import json
import os
import unittest

from investment_monitor.universe.ibkr_secdef import (
    IbkrSecdefError,
    contract_details,
    search_contracts,
)


class _FakeResponse:
    def __init__(self, payload):
        self._raw = json.dumps(payload).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def read(self):
        return self._raw


class _FakeOpener:
    def __init__(self, payload):
        self.payload = payload
        self.calls = 0

    def __call__(self, request, timeout=None):
        self.calls += 1
        return _FakeResponse(self.payload)


class IbkrSecdefTests(unittest.TestCase):
    def setUp(self):
        self.saved = {k: os.environ.get(k) for k in (
            "IBKR_SECDEF_BASE_URL", "IBKR_WEB_API_TOKEN"
        )}
        os.environ.pop("IBKR_SECDEF_BASE_URL", None)
        os.environ.pop("IBKR_WEB_API_TOKEN", None)

    def tearDown(self):
        for key, value in self.saved.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value

    def test_unconfigured_is_honest_mock_with_no_http(self):
        opener = _FakeOpener([])
        self.assertEqual(search_contracts("SAP", opener=opener), [])
        self.assertEqual(contract_details("123", opener=opener), {})
        self.assertEqual(opener.calls, 0)

    def test_base_url_without_token_also_skips(self):
        os.environ["IBKR_SECDEF_BASE_URL"] = "https://localhost:5000/v1/api"
        opener = _FakeOpener([])
        self.assertEqual(search_contracts("SAP", opener=opener), [])
        self.assertEqual(opener.calls, 0)

    def test_configured_search_normalizes_contract_fields(self):
        os.environ["IBKR_SECDEF_BASE_URL"] = "https://localhost:5000/v1/api"
        os.environ["IBKR_WEB_API_TOKEN"] = "test-token"
        payload = [{
            "conid": 123456, "symbol": "SAP", "description": "SAP SE",
            "companyName": "SAP SE", "assetType": "STK",
            "listingExchange": "IBIS", "currency": "EUR",
            "validExchanges": ["IBIS", "FWB"],
        }]
        rows = search_contracts(
            "SAP", exchange="IBIS", market="de",
            opener=_FakeOpener(payload),
        )
        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertEqual(row["conid"], "123456")
        self.assertEqual(row["symbol"], "SAP")
        self.assertEqual(row["localSymbol"], "SAP")
        self.assertEqual(row["secType"], "STK")
        self.assertEqual(row["currency"], "EUR")
        self.assertEqual(row["primaryExchange"], "IBIS")
        self.assertEqual(row["validExchanges"], ["IBIS", "FWB"])
        self.assertEqual(row["market"], "de")

    def test_session_supplies_connection_settings(self):
        class Session:
            base_url = "https://localhost:5000/v1/api"
            api_token = "session-token"

        rows = search_contracts(
            "EUNL", session=Session(),
            opener=_FakeOpener([{"conid": 99, "symbol": "EUNL"}]),
        )
        self.assertEqual(rows[0]["conid"], "99")

    def test_request_failure_raises_without_fabricating(self):
        os.environ["IBKR_SECDEF_BASE_URL"] = "https://localhost:5000/v1/api"
        os.environ["IBKR_WEB_API_TOKEN"] = "test-token"

        class BrokenOpener:
            def __call__(self, request, timeout=None):
                raise ConnectionError("boom")

        with self.assertRaises(IbkrSecdefError):
            search_contracts("SAP", opener=BrokenOpener())


if __name__ == "__main__":
    unittest.main()
