import json
from datetime import date
import unittest

from investment_monitor.models import CollectionRequest
from investment_monitor.registry import SOURCE_MARKETS, create_default_registry
from investment_monitor.sources.mops_disclosures import (
    MopsDisclosureClient,
    MopsDisclosureConnector,
    MopsDisclosureDataError,
)


class FakeResponse:
    def __init__(self, payload):
        self.payload = json.dumps(payload, ensure_ascii=False).encode()
    def __enter__(self): return self
    def __exit__(self, *args): return None
    def read(self): return self.payload


class QueueOpener:
    def __init__(self, payloads):
        self.payloads = list(payloads)
        self.calls = []
    def __call__(self, request, timeout=None):
        self.calls.append((request.full_url, json.loads(request.data)))
        return FakeResponse(self.payloads.pop(0))


def list_payload(rows):
    return {"code": 200, "message": "查詢成功", "result": {"data": rows}}


def detail_payload():
    return {"code": 200, "message": "查詢成功", "result": {"data": [[
        "1", "115/08/11", "18:03:01", "王小明", "發言人", "02-1234",
        "董事會決議", "第14款", "115/08/11", "完整說明",
    ]]}}


ROW = ["2330", "台積電", "115/08/11", "18:03:01", "董事會決議", {
    "apiName": "t05st01_detail",
    "parameters": {"marketKind": "sii", "companyId": "2330", "serialNumber": "1", "enterDate": "1150811"},
}]


class MopsDisclosureTests(unittest.TestCase):
    def test_registry_and_market_scope(self):
        self.assertEqual(SOURCE_MARKETS["mops_disclosures"], "tw")
        self.assertIn("mops_disclosures", create_default_registry().registered_names)

    def test_client_queries_month_and_maps_official_detail(self):
        opener = QueueOpener([list_payload([ROW]), detail_payload()])
        client = MopsDisclosureClient(opener=opener, requests_per_second=1000)
        records = client.fetch_by_ticker("2330", date(2026, 8, 1), date(2026, 8, 16))
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["external_id"], "mops:sii:2330:1150811:1")
        self.assertEqual(records[0]["classification"], "第14款")
        self.assertEqual(records[0]["summary"], "完整說明")
        self.assertEqual(opener.calls[0][1]["firstDay"], "1")
        self.assertEqual(opener.calls[0][1]["lastDay"], "16")

    def test_cross_month_window_is_split_without_duplicate(self):
        opener = QueueOpener([
            list_payload([ROW]), detail_payload(), list_payload([ROW]),
        ])
        client = MopsDisclosureClient(opener=opener, requests_per_second=1000)
        records = client.fetch_by_ticker("2330", date(2026, 7, 31), date(2026, 8, 16))
        self.assertEqual(len(records), 1)
        self.assertEqual([call[1]["month"] for call in opener.calls if call[0].endswith("t05st01")], ["7", "8"])

    def test_malformed_success_fails_closed(self):
        client = MopsDisclosureClient(
            opener=QueueOpener([{"code": 200, "message": "查詢成功", "result": {}}]),
            requests_per_second=1000,
        )
        with self.assertRaises(MopsDisclosureDataError):
            client.fetch_by_ticker("2330", date(2026, 8, 1), date(2026, 8, 2))

    def test_detail_identity_for_another_company_fails_closed(self):
        wrong = list(ROW)
        wrong_detail = dict(ROW[5])
        wrong_detail["parameters"] = {**ROW[5]["parameters"], "companyId": "2317"}
        wrong[5] = wrong_detail
        client = MopsDisclosureClient(
            opener=QueueOpener([list_payload([wrong])]),
            requests_per_second=1000,
        )
        with self.assertRaises(MopsDisclosureDataError):
            client.fetch_by_ticker("2330", date(2026, 8, 1), date(2026, 8, 2))

    def test_connector_maps_item_and_skips_foreign_market(self):
        class FakeClient:
            def __init__(self): self.calls = []
            def fetch_by_ticker(self, ticker, start, end):
                self.calls.append(ticker)
                opener = QueueOpener([list_payload([ROW]), detail_payload()])
                return MopsDisclosureClient(opener=opener, requests_per_second=1000).fetch_by_ticker(ticker, start, end)
        client = FakeClient()
        connector = MopsDisclosureConnector(client=client)
        request = CollectionRequest(
            tickers=("2330", "AAPL"), start_date=date(2026, 8, 1),
            end_date=date(2026, 8, 16), markets={"2330": "tw", "AAPL": "us"},
        )
        items = connector.collect(request)
        self.assertEqual(client.calls, ["2330"])
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0].market, "tw")
        self.assertEqual(items[0].raw_metadata["published_timezone"], "Asia/Taipei")
        self.assertEqual(connector.last_collection_status, "success")


if __name__ == "__main__":
    unittest.main()
