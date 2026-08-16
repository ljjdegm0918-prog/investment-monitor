"""EODHD client unit tests (fake opener, no network)."""

import os
import unittest

from investment_monitor.universe.eodhd_client import (
    EodhdClientError,
    collect_eodhd_symbols,
)


class _FakeResponse:
    def __init__(self, payload):
        import json
        self._raw = json.dumps(payload).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def read(self):
        return self._raw


class _FakeOpener:
    def __init__(self, responses):
        self.responses = responses
        self.urls = []

    def __call__(self, request, timeout=None):
        self.urls.append(request.full_url)
        key = request.full_url
        response = self.responses.get(key) or self.responses.get("default")
        if isinstance(response, Exception):
            raise response
        return _FakeResponse(response)


class EodhdClientTests(unittest.TestCase):
    def setUp(self):
        self.saved = os.environ.get("EODHD_API_KEY")
        os.environ["EODHD_API_KEY"] = "test-token"
        self.addCleanup(self._restore_env)

    def _restore_env(self):
        if self.saved is None:
            os.environ.pop("EODHD_API_KEY", None)
        else:
            os.environ["EODHD_API_KEY"] = self.saved

    def test_missing_token_is_a_noop(self):
        os.environ.pop("EODHD_API_KEY", None)
        rows, used = collect_eodhd_symbols(
            {"de": "XETRA"},
            {"limit": 20, "used_calls": 0, "refreshed_exchanges": []},
            opener=_FakeOpener({"default": []}),
        )
        self.assertEqual((rows, used), ([], 0))

    def test_budget_is_honoured(self):
        rows, used = collect_eodhd_symbols(
            {"de": "XETRA", "fr": "PAR"},
            {"limit": 20, "used_calls": 20, "refreshed_exchanges": []},
            opener=_FakeOpener({"default": []}),
        )
        self.assertEqual((rows, used), ([], 0))

    def test_rows_are_filtered_and_typed(self):
        payload = [
            {"Code": "EUNL", "Name": "iShares Core MSCI World", "Type": "ETF",
             "Exchange": "XETRA", "Currency": "EUR", "Isin": "IE00B4L5Y983"},
            {"Code": "SAP", "Name": "SAP SE", "Type": "Common Stock",
             "Exchange": "XETRA", "Currency": "EUR", "Isin": "DE0007164600"},
            {"Code": "BOND", "Name": "A bond", "Type": "Bond",
             "Exchange": "XETRA", "Currency": "EUR", "Isin": ""},
        ]
        budget = {"limit": 20, "used_calls": 0, "refreshed_exchanges": []}
        rows, used = collect_eodhd_symbols(
            {"de": "XETRA"},
            budget,
            opener=_FakeOpener({"default": payload}),
        )
        self.assertEqual(used, 1)
        self.assertEqual(budget["refreshed_exchanges"], ["XETRA"])
        self.assertEqual([r["symbol"] for r in rows], ["EUNL", "SAP"])
        self.assertEqual(rows[0]["instrument_type"], "etf")
        self.assertEqual(rows[1]["instrument_type"], "stock")
        self.assertEqual(rows[1]["isin"], "DE0007164600")
        self.assertEqual(rows[0]["source"], "eodhd:exchange_symbol_list")

    def test_partial_failure_keeps_rows(self):
        opener = _FakeOpener({
            "default": [],
        })
        # 按市场字典序先请求 XETRA，用按 URL 精确映射模拟部分失败。
        responses = {
            "https://eodhd.com/api/exchange-symbol-list/XETRA?api_token=test-token&fmt=json":
                [{"Code": "SAP", "Name": "SAP SE", "Type": "Common Stock"}],
        }
        opener = _FakeOpener(responses)
        opener.responses["default"] = ConnectionError("boom")
        budget = {"limit": 20, "used_calls": 0, "refreshed_exchanges": []}
        rows, used = collect_eodhd_symbols(
            {"de": "XETRA", "fr": "PAR"},
            budget,
            opener=opener,
        )
        self.assertEqual(used, 2)
        self.assertEqual([r["symbol"] for r in rows], ["SAP"])
        # 只有成功刷完的交易所进入已刷新集合。
        self.assertEqual(budget["refreshed_exchanges"], ["XETRA"])

    def test_duplicate_exchange_codes_are_fetched_once(self):
        budget = {"limit": 20, "used_calls": 0, "refreshed_exchanges": []}
        rows, used = collect_eodhd_symbols(
            {"gb": "LSE", "uk": "LSE"},
            budget,
            opener=_FakeOpener({"default": []}),
        )
        self.assertEqual((rows, used), ([], 1))
        self.assertEqual(budget["refreshed_exchanges"], ["LSE"])

    def test_total_failure_raises_and_consumes_budget(self):
        budget = {"limit": 5, "used_calls": 0, "refreshed_exchanges": []}
        with self.assertRaises(EodhdClientError):
            collect_eodhd_symbols(
                {"de": "XETRA", "fr": "PAR"},
                budget,
                opener=_FakeOpener({"default": ConnectionError("boom")}),
            )
        self.assertEqual(budget["used_calls"], 2)
        self.assertEqual(budget["refreshed_exchanges"], [])


if __name__ == "__main__":
    unittest.main()
