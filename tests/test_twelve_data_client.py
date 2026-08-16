"""Twelve Data optional client unit tests (fake opener, no network)."""

import json
import os
import unittest

from investment_monitor.universe.twelve_data_client import (
    enrich_with_twelve_quotes,
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


class TwelveDataClientTests(unittest.TestCase):
    def setUp(self):
        self.saved = os.environ.get("TWELVE_DATA_API_KEY")
        os.environ.pop("TWELVE_DATA_API_KEY", None)
        self.addCleanup(self._restore_env)

    def _restore_env(self):
        if self.saved is not None:
            os.environ["TWELVE_DATA_API_KEY"] = self.saved

    def test_no_key_returns_candidates_unchanged(self):
        candidates = [
            {"market": "de", "symbol": "EUNL", "name": "EUNL", "isin": ""},
        ]
        rows = enrich_with_twelve_quotes(candidates)
        self.assertEqual(rows, candidates)
        self.assertNotIn("twelve_data_mic_code", rows[0])

    def test_keyless_opt_in_enriches_provenance_fields(self):
        candidates = [
            {"market": "de", "symbol": "EUNL", "name": "EUNL", "isin": "",
             "instrument_type": "etf"},
        ]
        payload = {"status": "ok", "data": [
            {"symbol": "EUNL", "instrument_name": "iShares Core MSCI World",
             "exchange": "XETRA", "mic_code": "XETR",
             "instrument_type": "ETF", "country": "Ireland",
             "currency": "EUR"},
        ]}

        class Opener:
            def __call__(self, request, timeout=None):
                return _FakeResponse(payload)

        rows = enrich_with_twelve_quotes(
            candidates,
            allow_no_key=True,
            opener=Opener(),
            pause_seconds=0,
        )
        self.assertEqual(rows[0]["twelve_data_mic_code"], "XETR")
        self.assertEqual(rows[0]["twelve_data_instrument_type"], "ETF")


if __name__ == "__main__":
    unittest.main()
