from datetime import date, datetime, timedelta, timezone
from io import BytesIO
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch
from urllib.error import HTTPError
import zipfile

from investment_monitor.sources.edinet import (
    EDINETClient, EDINETCompanyInput, EDINETConnector, EDINETRequestError,
    EDINETStore,
)
from investment_monitor.sources.edinet.connector import (
    EDINETDataError,
    _read_limited_response,
)
from investment_monitor.models import CollectionRequest


def record(doc_id, submitted, *, edinet="E00001", sec="72030", dtype="999",
           issuer=None, subject=None, withdrawn="0"):
    return {
        "docID": doc_id, "edinetCode": edinet, "secCode": sec,
        "JCN": "1234567890123", "filerName": "テスト株式会社",
        "docTypeCode": dtype, "docDescription": f"type {dtype}",
        "submitDateTime": submitted, "issuerEdinetCode": issuer,
        "subjectEdinetCode": subject, "withdrawalStatus": withdrawn,
        "xbrlFlag": "1", "pdfFlag": "1",
    }


class FakeClient:
    def __init__(self, responses):
        self.responses = responses
        self.calls = []

    def list_documents(self, day):
        self.calls.append(day)
        response = self.responses[day]
        if isinstance(response, Exception):
            raise response
        return {"results": response}

    def download_document(self, doc_id, download_type):
        stream = BytesIO()
        with zipfile.ZipFile(stream, "w") as archive:
            archive.writestr("document.txt", "official fixture")
        return stream.getvalue(), "application/octet-stream"


class EDINETConnectorTests(unittest.TestCase):
    def make_connector(self, responses, now):
        temporary = TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        return EDINETConnector(FakeClient(responses), EDINETStore(root / "edinet.db"),
            cache_ttl=timedelta(seconds=60), download_root=root / "downloads",
            now=lambda: now)

    def test_login_feed_crosses_japan_dates_keeps_all_types_and_roles(self):
        now = datetime(2026, 8, 8, 3, tzinfo=timezone.utc)
        connector = self.make_connector({
            date(2026, 8, 7): [
                record("OLD", "2026-08-07 11:59", dtype="120"),
                record("SUBJECT", "2026-08-07 13:00", edinet="E99999",
                       sec="99990", dtype="350", subject="E00001"),
            ],
            date(2026, 8, 8): [
                record("NEW", "2026-08-08 10:00", dtype="999"),
                record("WITHDRAWN", "2026-08-08 09:00", withdrawn="1"),
            ],
        }, now)

        result = connector.getWatchlistDisclosuresSince(
            companies=[{"edinetCode": "E00001"}],
            since=now - timedelta(hours=24), now=now,
        )

        self.assertEqual([item.doc_id for item in result.items], ["NEW", "SUBJECT"])
        self.assertEqual(result.items[0].doc_type_code, "999")
        self.assertEqual(result.items[1].match_roles, ("subject",))
        self.assertEqual(result.items[1].matched_edinet_codes, ("E00001",))
        self.assertEqual(result.counts_by_company, {"E00001": 2})
        self.assertFalse(result.unresolved)
        self.assertEqual(connector.client.calls, [date(2026, 8, 7), date(2026, 8, 8)])

    def test_cache_avoids_login_storm_and_partial_date_error_is_returned(self):
        now = datetime(2026, 8, 8, 3, tzinfo=timezone.utc)
        connector = self.make_connector({
            date(2026, 8, 7): [record("ONE", "2026-08-07 13:00")],
            date(2026, 8, 8): EDINETRequestError("temporary", 503),
        }, now)
        kwargs = dict(companies=["E00001"], since=now-timedelta(hours=24), now=now)

        first = connector.get_watchlist_disclosures_since(**kwargs)
        second = connector.get_watchlist_disclosures_since(**kwargs)

        self.assertTrue(first.partial)
        self.assertEqual(first.items[0].doc_id, "ONE")
        self.assertEqual(len(first.errors), 1)
        self.assertEqual(connector.client.calls.count(date(2026, 8, 7)), 1)
        self.assertEqual(connector.client.calls.count(date(2026, 8, 8)), 1)
        self.assertTrue(second.partial)

    def test_source_wide_collection_status_matrix_preserves_date_failures(self):
        now = datetime(2026, 8, 8, 3, tzinfo=timezone.utc)
        first_day = date(2026, 8, 7)
        second_day = date(2026, 8, 8)
        scenarios = {
            "partial_with_items": (
                {
                    first_day: [record("ONE", "2026-08-07 13:00")],
                    second_day: EDINETRequestError("second day blocked", 503),
                },
                "partial",
                1,
                1,
            ),
            "partial_without_items": (
                {
                    first_day: [],
                    second_day: EDINETRequestError("second day blocked", 503),
                },
                "partial",
                0,
                1,
            ),
            "all_failure": (
                {
                    first_day: EDINETRequestError("first day blocked", 503),
                    second_day: EDINETRequestError("second day blocked", 503),
                },
                "failure",
                0,
                2,
            ),
            "success": (
                {
                    first_day: [record("ONE", "2026-08-07 13:00")],
                    second_day: [],
                },
                "success",
                1,
                0,
            ),
            "empty": (
                {first_day: [], second_day: []},
                "empty",
                0,
                0,
            ),
        }
        request = CollectionRequest(
            tickers=("7203",),
            start_date=first_day,
            end_date=second_day,
            markets={"7203": "jp"},
        )
        for label, (responses, status, item_count, failure_count) in scenarios.items():
            with self.subTest(label=label):
                connector = self.make_connector(responses, now)

                items = connector.collect(request)

                self.assertEqual(len(items), item_count)
                self.assertEqual(connector.last_collection_status, status)
                self.assertEqual(connector.last_records_read, item_count)
                self.assertEqual(
                    len(connector.last_failure_details), failure_count
                )
                failed_dates = {
                    detail["feed"] for detail in connector.last_failure_details
                }
                self.assertEqual(
                    failed_dates,
                    (
                        {first_day.isoformat(), second_day.isoformat()}
                        if failure_count == 2
                        else {second_day.isoformat()}
                        if failure_count == 1
                        else set()
                    ),
                )
                if failure_count:
                    self.assertTrue(all(
                        "blocked" in detail["message"]
                        for detail in connector.last_failure_details
                    ))

    def test_code_resolution_and_download_integrity(self):
        now = datetime(2026, 8, 8, 3, tzinfo=timezone.utc)
        connector = self.make_connector({date(2026,8,8): [record("ZIP", "2026-08-08 10:00")]}, now)
        connector.store.replace_codes([{
            "ＥＤＩＮＥＴコード":"E00001", "提出者名":"テスト株式会社",
            "証券コード":"72030", "法人番号":"1234567890123",
        }], now)
        resolved = connector.resolveCompanies(["7203"])
        connector.sync_range(date(2026,8,8), date(2026,8,8))
        downloads = connector.downloadDocument("ZIP", [1])

        self.assertEqual(resolved["resolved"][0].edinet_code, "E00001")
        self.assertEqual(downloads[0].status, "stored")
        self.assertTrue(downloads[0].zip_valid)
        self.assertTrue(downloads[0].path.exists())

    def test_client_retries_429_without_leaking_key(self):
        class Response:
            headers = {"Content-Type": "application/json"}
            def __init__(self):
                self.done = False
            def __enter__(self): return self
            def __exit__(self, *args): return None
            def read(self, size=-1):
                if self.done:
                    return b""
                self.done = True
                return json.dumps({"results": []}).encode()
        calls = []
        def opener(request, timeout):
            calls.append(request)
            if len(calls) == 1:
                raise HTTPError(request.full_url, 429, "rate", {}, None)
            return Response()
        client = EDINETClient("secret-key", opener=opener, sleeper=lambda _: None,
                              clock=lambda: 0, requests_per_second=1)

        payload = client.list_documents(date(2026,8,8))

        self.assertEqual(payload["results"], [])
        self.assertEqual(len(calls), 2)
        self.assertNotIn("secret-key", calls[0].full_url)
        self.assertEqual(calls[0].headers["Ocp-apim-subscription-key"], "secret-key")

    def test_read_limited_accepts_small_body_and_rejects_oversize(self):
        class SmallResponse:
            headers = {}
            def __init__(self):
                self.done = False
            def read(self, size=-1):
                if self.done:
                    return b""
                self.done = True
                return b"small"

        with patch(
            "investment_monitor.sources.edinet.connector.EDINET_MAX_RESPONSE_BYTES",
            16,
        ):
            self.assertEqual(_read_limited_response(SmallResponse()), b"small")

            class OversizeResponse:
                headers = {"Content-Length": "17"}
                def read(self, size=-1):
                    return b"x" * 17

            with self.assertRaises(EDINETDataError):
                _read_limited_response(OversizeResponse())

            class StreamingResponse:
                headers = {}
                def __init__(self):
                    self.remaining = 20
                def read(self, size=-1):
                    if self.remaining <= 0:
                        return b""
                    chunk = b"x" * min(size, self.remaining)
                    self.remaining -= len(chunk)
                    return chunk

            with self.assertRaises(EDINETDataError):
                _read_limited_response(StreamingResponse())

    def test_download_document_rejects_unsafe_doc_id(self):
        now = datetime(2026, 8, 8, 3, tzinfo=timezone.utc)
        connector = self.make_connector({}, now)
        for bad in ("../etc/passwd", "a/b", "foo.bar", "x y", ""):
            with self.subTest(doc_id=bad):
                with self.assertRaises(ValueError):
                    connector.download_document(
                        bad, types=(1,), file_date=date(2026, 8, 8)
                    )


if __name__ == "__main__":
    unittest.main()
