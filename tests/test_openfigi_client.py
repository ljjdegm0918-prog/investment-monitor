"""OpenFIGI client unit tests (fake opener, no network)."""

import json
import unittest

from investment_monitor.universe.openfigi_client import enrich_with_openfigi


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
    def __init__(self, payload, requests=1):
        self.payload = payload
        self.requests = requests
        self.calls = 0

    def __call__(self, request, timeout=None):
        self.calls += 1
        if self.calls > self.requests:
            raise ConnectionError("rate-limited in test")
        return _FakeResponse(self.payload)


class OpenFigiClientTests(unittest.TestCase):
    def test_figi_added_only_for_etf_rows_missing_isin(self):
        candidates = [
            {"market": "de", "symbol": "EUNL", "name": "EUNL", "isin": "",
             "instrument_type": "etf", "exchange": "XETRA"},
            {"market": "de", "symbol": "SAP", "name": "SAP SE",
             "isin": "DE0007164600", "instrument_type": "stock",
             "exchange": "XETRA"},
        ]
        payload = [
            {"data": [{"figi": "BBG00ABC", "name": "iShares Core MSCI World",
                       "exchCode": "SW", "securityType": "ETF"}]},
        ]
        rows = enrich_with_openfigi(
            candidates,
            opener=_FakeOpener(payload),
            pause_seconds=0,
        )
        self.assertEqual(rows[0]["figi"], "BBG00ABC")
        self.assertEqual(rows[0]["figi_security_type"], "ETF")
        self.assertNotIn("figi", rows[1])

    def test_no_data_result_leaves_row_untouched(self):
        candidates = [
            {"market": "de", "symbol": "NOPE", "name": "NOPE", "isin": "",
             "instrument_type": "etf", "exchange": "XETRA"},
        ]
        rows = enrich_with_openfigi(
            candidates,
            opener=_FakeOpener([{"warning": "No identifier found."}]),
            pause_seconds=0,
        )
        self.assertNotIn("figi", rows[0])
        self.assertEqual(rows[0]["symbol"], "NOPE")

    def test_batches_are_sent_in_chunks(self):
        candidates = [
            {"market": "de", "symbol": f"ETF{i}", "name": f"ETF{i}",
             "isin": "", "instrument_type": "etf", "exchange": "XETRA"}
            for i in range(25)
        ]
        opener = _FakeOpener([{"data": []}], requests=3)
        rows = enrich_with_openfigi(
            candidates,
            opener=opener,
            jobs_per_request=10,
            pause_seconds=0,
        )
        self.assertEqual(len(rows), 25)
        self.assertEqual(opener.calls, 3)


if __name__ == "__main__":
    unittest.main()
