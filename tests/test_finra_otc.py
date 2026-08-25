"""FINRA public OTC universe and Daily List tests (offline fixtures)."""

from datetime import date
import json
from pathlib import Path
import unittest

from investment_monitor.models import CollectionRequest
from investment_monitor.sources.finra_otc_daily_list import (
    FinraOtcDailyListConnector,
)
from investment_monitor.universe.finra_otc import (
    FinraOtcClient,
    FinraOtcDataError,
)


FIXTURES = Path(__file__).parent / "fixtures" / "finra_otc"


class _Response:
    def __init__(self, payload, headers=None):
        self._body = json.dumps(payload).encode("utf-8")
        self.headers = headers or {}

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self):
        return self._body


class _Opener:
    def __init__(self, *, drift=False, repeat=False):
        self.drift = drift
        self.repeat = repeat
        self.requests = []
        self.security_rows = json.loads(
            (FIXTURES / "security_rows.json").read_text(encoding="utf-8")
        )
        self.daily_rows = json.loads(
            (FIXTURES / "daily_rows.json").read_text(encoding="utf-8")
        )

    def __call__(self, request, timeout=None):
        self.requests.append(request)
        url = request.full_url
        if "/partitions/" in url:
            name = "daily_partitions.json" if url.endswith("otcDailyList") else "security_partitions.json"
            return _Response(json.loads((FIXTURES / name).read_text(encoding="utf-8")))
        body = json.loads(request.data.decode("utf-8"))
        rows = self.daily_rows if url.endswith("otcDailyList") else self.security_rows
        offset, limit = int(body["offset"]), int(body["limit"])
        expected = max(0, min(limit, len(rows) - offset))
        page = rows[0:expected] if self.repeat and offset else rows[offset:offset + limit]
        total = len(rows) + (1 if self.drift and offset else 0)
        return _Response(page, {
            "record-total": str(total),
            "record-limit": str(limit),
            "record-offset": str(offset),
            "record-max-limit": "5000",
        })


class FinraOtcTests(unittest.TestCase):
    def client(self, opener):
        return FinraOtcClient(
            opener=opener,
            requests_per_second=1000,
            sleeper=lambda _seconds: None,
        )

    def test_security_master_reconciles_two_pages(self):
        opener = _Opener()
        as_of, rows = self.client(opener).fetch_active_security_master(
            page_size=2,
        )
        self.assertEqual(as_of, "2026-08-24")
        self.assertEqual([row["ticker"] for row in rows], ["AABB", "AACAY", "ABCDW"])
        self.assertEqual(len(opener.requests), 3)

    def test_total_drift_and_repeated_page_fail_closed(self):
        with self.assertRaisesRegex(FinraOtcDataError, "drifted"):
            self.client(_Opener(drift=True)).fetch_active_security_master(page_size=2)
        with self.assertRaisesRegex(FinraOtcDataError, "repeated symbol"):
            self.client(_Opener(repeat=True)).fetch_active_security_master(page_size=2)

    def test_page_cap_fails_before_returning_partial_data(self):
        with self.assertRaisesRegex(FinraOtcDataError, "exceeds max_pages"):
            self.client(_Opener()).fetch_active_security_master(
                page_size=1,
                max_pages=2,
            )

    def test_daily_list_connector_matches_only_verified_otc_symbols(self):
        opener = _Opener()
        client = self.client(opener)
        connector = FinraOtcDailyListConnector(
            client,
            universe={
                "LRBI": {"name": "Example Bancorp", "otc": True},
                "AAPL": {"name": "Apple", "otc": False},
            },
        )
        request = CollectionRequest(
            tickers=("LRBI", "AAPL"),
            start_date=date(2026, 8, 24),
            end_date=date(2026, 8, 24),
            markets={"LRBI": "us", "AAPL": "us"},
        )
        items = connector.collect(request)
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0].document_type, "dividend")
        self.assertEqual(items[0].published_at.isoformat(), "2026-08-24T16:15:00-04:00")
        self.assertEqual(items[0].raw_metadata["cash_amount"], "0.12")
        self.assertTrue(items[0].raw_metadata["official_document"])
        self.assertEqual(connector.last_collection_status, "success")
        self.assertEqual(connector.last_records_read, 3)

    def test_exchange_listed_only_request_uses_zero_http(self):
        opener = _Opener()
        connector = FinraOtcDailyListConnector(
            self.client(opener),
            universe={"AAPL": {"name": "Apple", "otc": False}},
        )
        request = CollectionRequest(
            tickers=("AAPL",),
            start_date=date(2026, 8, 24),
            end_date=date(2026, 8, 24),
            markets={"AAPL": "us"},
        )
        self.assertEqual(connector.collect(request), [])
        self.assertEqual(opener.requests, [])

    def test_missing_default_universe_is_unavailable_not_empty(self):
        connector = FinraOtcDailyListConnector(self.client(_Opener()), universe={})
        connector._universe_ready = False
        request = CollectionRequest(
            tickers=("AABB",),
            start_date=date(2026, 8, 24),
            end_date=date(2026, 8, 24),
            markets={"AABB": "us"},
        )
        with self.assertRaisesRegex(Exception, "universe cache is unavailable"):
            connector.collect(request)
        self.assertEqual(connector.last_collection_status, "unavailable")


if __name__ == "__main__":
    unittest.main()
