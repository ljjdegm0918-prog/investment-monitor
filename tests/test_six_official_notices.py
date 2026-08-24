"""Offline contract tests for the public SIX/SER Official Notices source."""

from __future__ import annotations

from datetime import date
from io import BytesIO
import json
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import parse_qs, urlparse
import unittest

from investment_monitor import CollectionRequest
from investment_monitor.registry import create_default_registry
from investment_monitor.sources.six_official_notices import (
    SixOfficialNoticesClient,
    SixOfficialNoticesConnector,
    SixOfficialNoticesDataError,
    SixOfficialNoticesRequestError,
)

FIXTURES = Path(__file__).parent / "fixtures" / "six_official_notices"


class _Response:
    def __init__(self, payload: object) -> None:
        self._body = json.dumps(payload).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return None

    def read(self) -> bytes:
        return self._body


def _fixture(name: str):
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def _opener(request, **_kwargs):
    parsed = urlparse(request.full_url)
    if "/find.json" in parsed.path:
        query = parse_qs(parsed.query)
        page = int(query["pageNumber"][0])
        if int(query["pageSize"][0]) >= 3 and page == 0:
            combined = _fixture("list_page_1.json")
            combined["itemList"].extend(_fixture("list_page_2.json")["itemList"])
            return _Response(combined)
        return _Response(_fixture(f"list_page_{page + 1}.json"))
    notice_id = parsed.path.rsplit("/", 1)[-1].removesuffix(".json")
    return _Response(_fixture(f"detail_{notice_id}.json"))


class SixOfficialNoticesClientTests(unittest.TestCase):
    def test_compound_and_non_isin_labels_match_without_corrupting_identity(self) -> None:
        def opener(request, **_kwargs):
            parsed = urlparse(request.full_url)
            if "/find.json" in parsed.path:
                payload = _fixture("list_page_1.json")
                payload["itemList"].extend(
                    _fixture("list_page_2.json")["itemList"]
                )
                payload["itemList"][0]["isin"] = (
                    "CH0038863350 / CH1589255814"
                )
                payload["itemList"][1]["isin"] = "Part I"
                return _Response(payload)
            detail = _fixture("detail_360101.json")
            detail["itemList"][0]["isin"] = (
                "CH0038863350 / CH1589255814"
            )
            return _Response(detail)

        records = SixOfficialNoticesClient(
            opener=opener,
            requests_per_second=1000,
            sleeper=lambda _seconds: None,
        ).fetch_for_isins(
            ("CH0038863350",),
            date(2026, 8, 13),
            date(2026, 8, 14),
        )

        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["matched_isins"], ["CH0038863350"])
        self.assertEqual(
            records[0]["isins"], ["CH0038863350", "CH1589255814"]
        )
        self.assertEqual(
            records[0]["isin_raw"], "CH0038863350 / CH1589255814"
        )

    def test_complete_pagination_matches_isins_before_fetching_details(self) -> None:
        calls = []

        def opener(request, **kwargs):
            calls.append(request.full_url)
            return _opener(request, **kwargs)

        client = SixOfficialNoticesClient(
            opener=opener,
            requests_per_second=1000,
            sleeper=lambda _seconds: None,
        )
        records = client.fetch_for_isins(
            ("CH0038863350", "CH0012032048"),
            date(2026, 8, 13),
            date(2026, 8, 14),
            page_size=2,
        )

        self.assertEqual([item["notice_id"] for item in records], [360101, 360099])
        self.assertEqual(client.last_list_records, 3)
        self.assertEqual(client.last_matched_records, 2)
        self.assertEqual(len([url for url in calls if "/details/" in url]), 2)
        self.assertFalse(any("360100" in url for url in calls))
        self.assertEqual(records[0]["published_at"].isoformat(), "2026-08-14T07:30:05+02:00")
        self.assertIn("Dividend ex-date", records[0]["summary"])

    def test_total_drift_overlap_and_page_cap_fail_closed(self) -> None:
        changed = _fixture("list_page_2.json")
        changed["totalCount"] = 4

        def drift(request, **_kwargs):
            page = int(parse_qs(urlparse(request.full_url).query)["pageNumber"][0])
            return _Response(_fixture("list_page_1.json") if page == 0 else changed)

        with self.assertRaisesRegex(SixOfficialNoticesDataError, "drifted"):
            SixOfficialNoticesClient(
                opener=drift,
                requests_per_second=1000,
                sleeper=lambda _seconds: None,
            ).fetch_for_isins(
                ("CH0038863350",),
                date(2026, 8, 13),
                date(2026, 8, 14),
                page_size=2,
            )

        overlap = _fixture("list_page_2.json")
        overlap["itemList"][0]["noticeId"] = 360101

        def repeated(request, **_kwargs):
            page = int(parse_qs(urlparse(request.full_url).query)["pageNumber"][0])
            return _Response(_fixture("list_page_1.json") if page == 0 else overlap)

        with self.assertRaisesRegex(SixOfficialNoticesDataError, "repeated"):
            SixOfficialNoticesClient(
                opener=repeated,
                requests_per_second=1000,
                sleeper=lambda _seconds: None,
            ).fetch_for_isins(
                ("CH0038863350",),
                date(2026, 8, 13),
                date(2026, 8, 14),
                page_size=2,
            )

        with self.assertRaisesRegex(SixOfficialNoticesDataError, "max_pages=1"):
            SixOfficialNoticesClient(
                opener=_opener,
                requests_per_second=1000,
                sleeper=lambda _seconds: None,
            ).fetch_for_isins(
                ("CH0038863350",),
                date(2026, 8, 13),
                date(2026, 8, 14),
                page_size=2,
                max_pages=1,
            )

    def test_bad_detail_empty_envelope_html_and_http_fail(self) -> None:
        bad_detail = _fixture("detail_360101.json")
        bad_detail["itemList"][0]["noticeId"] = 999

        def wrong_detail(request, **kwargs):
            if "/details/360101" in request.full_url:
                return _Response(bad_detail)
            return _opener(request, **kwargs)

        with self.assertRaisesRegex(SixOfficialNoticesDataError, "identity"):
            SixOfficialNoticesClient(
                opener=wrong_detail,
                requests_per_second=1000,
                sleeper=lambda _seconds: None,
            ).fetch_for_isins(
                ("CH0038863350",),
                date(2026, 8, 13),
                date(2026, 8, 14),
                page_size=2,
            )

        missing_isin = _fixture("detail_360101.json")
        missing_isin["itemList"][0]["isin"] = "Part I"

        def detail_without_isin(request, **kwargs):
            if "/details/360101" in request.full_url:
                return _Response(missing_isin)
            return _opener(request, **kwargs)

        with self.assertRaisesRegex(SixOfficialNoticesDataError, "ISINs"):
            SixOfficialNoticesClient(
                opener=detail_without_isin,
                requests_per_second=1000,
                sleeper=lambda _seconds: None,
            ).fetch_for_isins(
                ("CH0038863350",),
                date(2026, 8, 13),
                date(2026, 8, 14),
                page_size=2,
            )

        class HtmlResponse(_Response):
            def __init__(self):
                self._body = b"<html>Loading...</html>"

        with self.assertRaisesRegex(SixOfficialNoticesDataError, "non-JSON"):
            SixOfficialNoticesClient(
                opener=lambda *_args, **_kwargs: HtmlResponse(),
                requests_per_second=1000,
                sleeper=lambda _seconds: None,
            ).fetch_for_isins(
                ("CH0038863350",),
                date(2026, 8, 14),
                date(2026, 8, 14),
            )

        def forbidden(request, **_kwargs):
            raise HTTPError(request.full_url, 403, "Forbidden", {}, BytesIO())

        with self.assertRaisesRegex(SixOfficialNoticesRequestError, "HTTP 403"):
            SixOfficialNoticesClient(
                opener=forbidden,
                max_retries=3,
                requests_per_second=1000,
                sleeper=lambda _seconds: None,
            ).fetch_for_isins(
                ("CH0038863350",),
                date(2026, 8, 14),
                date(2026, 8, 14),
            )


class SixOfficialNoticesConnectorTests(unittest.TestCase):
    def test_connector_maps_exact_isin_and_preserves_official_provenance(self) -> None:
        client = SixOfficialNoticesClient(
            opener=_opener,
            requests_per_second=1000,
            sleeper=lambda _seconds: None,
        )
        connector = SixOfficialNoticesConnector(
            client=client,
            universe={
                "NESN": {"name": "Nestlé S.A.", "isin": "CH0038863350"},
            },
        )
        items = connector.collect(
            CollectionRequest(
                tickers=("NESN.SW",),
                start_date=date(2026, 8, 13),
                end_date=date(2026, 8, 14),
                markets={"NESN.SW": "ch"},
            )
        )

        self.assertEqual(len(items), 1)
        item = items[0]
        self.assertEqual(item.source, "six_official_notices")
        self.assertEqual(item.tickers, ("NESN",))
        self.assertEqual(item.external_id, "six-notice:360101")
        self.assertEqual(item.raw_metadata["source_tier"], 1)
        self.assertTrue(item.raw_metadata["official_document"])
        self.assertEqual(item.raw_metadata["isin"], "CH0038863350")
        self.assertIn("/details/360101.json", item.raw_metadata["retrieval_url"])
        self.assertEqual(connector.last_collection_status, "success")
        self.assertEqual(connector.last_records_read, 3)

    def test_missing_isin_is_not_success_and_registry_is_wired(self) -> None:
        connector = SixOfficialNoticesConnector(client=object(), universe={})
        items = connector.collect(
            CollectionRequest(
                tickers=("UNKNOWN",),
                start_date=date(2026, 8, 14),
                end_date=date(2026, 8, 14),
                markets={"UNKNOWN": "ch"},
            )
        )
        self.assertEqual(items, [])
        self.assertEqual(connector.last_collection_status, "unavailable")
        self.assertEqual(connector.last_errors, (("UNKNOWN", "no_universe_isin"),))
        self.assertIsNotNone(
            create_default_registry().factory_for("six_official_notices")
        )


if __name__ == "__main__":
    unittest.main()
