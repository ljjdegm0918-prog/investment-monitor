from __future__ import annotations

import io
import json
import unittest
from datetime import date
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from investment_monitor.models import CollectionRequest
from investment_monitor.sources.nasdaq_se import (
    NasdaqSeClient,
    NasdaqSeDataError,
    NasdaqSeFilingsConnector,
)


FIXTURES = Path(__file__).parent / "fixtures" / "se_universe"


class _Response(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


class NasdaqSeClientTests(unittest.TestCase):
    def test_share_directory_combines_main_and_first_north(self) -> None:
        payloads = [
            json.loads((FIXTURES / "main_market.json").read_text()),
            json.loads((FIXTURES / "first_north.json").read_text()),
        ]
        requests = []

        def opener(request, timeout):
            requests.append(request.full_url)
            return _Response(json.dumps(payloads.pop(0)).encode())

        rows = NasdaqSeClient(opener=opener, requests_per_second=1000000).fetch_share_directory()
        self.assertEqual([row["symbol"] for row in rows], ["ERIC B", "VOLV B", "AAC", "EMIL B"])
        self.assertEqual(
            [row["listing_category"] for row in rows],
            ["MAIN_MARKET", "MAIN_MARKET", "FIRST_NORTH", "FIRST_NORTH"],
        )
        first = parse_qs(urlsplit(requests[0]).query)
        self.assertEqual(first["market"], ["STO"])
        self.assertEqual(first["category"], ["MAIN_MARKET"])
        self.assertNotIn("assetClass", first)
        self.assertEqual(first["size"], ["1000"])
        self.assertEqual(first["page"], ["1"])
        self.assertEqual(rows[0]["listing_market"], "STO")

    def test_share_directory_rejects_incomplete_pagination(self) -> None:
        payload = json.loads((FIXTURES / "main_market.json").read_text())
        payload["data"]["pagination"]["total"] = 3

        def opener(request, timeout):
            return _Response(json.dumps(payload).encode())

        with self.assertRaisesRegex(NasdaqSeDataError, "row count"):
            NasdaqSeClient(opener=opener, requests_per_second=1000000).fetch_share_directory()

    def test_share_directory_rejects_cross_page_identity_overlap(self) -> None:
        first = json.loads((FIXTURES / "main_market.json").read_text())
        first["data"]["instrumentListing"]["rows"] = first["data"][
            "instrumentListing"
        ]["rows"][:1]
        first["data"]["pagination"] = {
            "total": 2,
            "size": 1,
            "page": 1,
            "totalPages": 2,
        }
        second = json.loads(json.dumps(first))
        second["data"]["pagination"]["page"] = 2
        payloads = [first, second]

        def opener(request, timeout):
            return _Response(json.dumps(payloads.pop(0)).encode())

        with self.assertRaisesRegex(NasdaqSeDataError, "overlapped identities"):
            NasdaqSeClient(
                opener=opener,
                requests_per_second=1000000,
            ).fetch_share_directory(page_size=1)

    def test_share_directory_rejects_status_and_page_cap(self) -> None:
        bad_status = json.loads((FIXTURES / "main_market.json").read_text())
        bad_status["status"]["rCode"] = 503

        def status_opener(request, timeout):
            return _Response(json.dumps(bad_status).encode())

        with self.assertRaisesRegex(NasdaqSeDataError, "status was 503"):
            NasdaqSeClient(
                opener=status_opener,
                requests_per_second=1000000,
            ).fetch_share_directory()

        first = json.loads((FIXTURES / "main_market.json").read_text())
        first["data"]["instrumentListing"]["rows"] = first["data"][
            "instrumentListing"
        ]["rows"][:1]
        first["data"]["pagination"] = {
            "total": 2,
            "size": 1,
            "page": 1,
            "totalPages": 2,
        }

        def capped_opener(request, timeout):
            return _Response(json.dumps(first).encode())

        with self.assertRaisesRegex(NasdaqSeDataError, "exceeded max_pages=1"):
            NasdaqSeClient(
                opener=capped_opener,
                requests_per_second=1000000,
            ).fetch_share_directory(page_size=1, max_pages=1)

    def test_share_directory_rejects_pagination_drift(self) -> None:
        first = json.loads((FIXTURES / "main_market.json").read_text())
        rows = first["data"]["instrumentListing"]["rows"]
        first["data"]["instrumentListing"]["rows"] = rows[:1]
        first["data"]["pagination"] = {
            "total": 2,
            "size": 1,
            "page": 1,
            "totalPages": 2,
        }
        second = json.loads(json.dumps(first))
        second["data"]["instrumentListing"]["rows"] = rows[1:2]
        second["data"]["pagination"] = {
            "total": 3,
            "size": 1,
            "page": 2,
            "totalPages": 3,
        }
        payloads = [first, second]

        def opener(request, timeout):
            return _Response(json.dumps(payloads.pop(0)).encode())

        with self.assertRaisesRegex(NasdaqSeDataError, "drifted between pages"):
            NasdaqSeClient(
                opener=opener,
                requests_per_second=1000000,
            ).fetch_share_directory(page_size=1)

    def test_share_directory_completes_two_pages_for_both_categories(self) -> None:
        payloads = []
        for filename in ("main_market.json", "first_north.json"):
            source = json.loads((FIXTURES / filename).read_text())
            rows = source["data"]["instrumentListing"]["rows"]
            for page, row in enumerate(rows, start=1):
                payload = json.loads(json.dumps(source))
                payload["data"]["instrumentListing"]["rows"] = [row]
                payload["data"]["pagination"] = {
                    "total": 2,
                    "size": 1,
                    "page": page,
                    "totalPages": 2,
                }
                payloads.append(payload)
        requests = []

        def opener(request, timeout):
            requests.append(request.full_url)
            return _Response(json.dumps(payloads.pop(0)).encode())

        rows = NasdaqSeClient(
            opener=opener,
            requests_per_second=1000000,
        ).fetch_share_directory(page_size=1)

        self.assertEqual(len(rows), 4)
        self.assertEqual(sum("page=2" in url for url in requests), 2)

    def test_paginates_to_declared_count(self) -> None:
        payloads = [
            {"results": {"item": [
                {"disclosureId": 1, "published": "2026-08-01 07:00:00"},
                {"disclosureId": 2, "published": "2026-08-02 07:00:00"},
            ]}, "count": 3},
            {"results": {"item": [{"disclosureId": 3, "published": "2026-08-03 07:00:00"}]}, "count": 3},
        ]

        def opener(request, timeout):
            return _Response(json.dumps(payloads.pop(0)).encode())

        records = NasdaqSeClient(opener=opener, requests_per_second=1000000).fetch_announcements(
            "Ericsson, Telefonab. L M",
            date(2026, 8, 1),
            date(2026, 8, 15),
            global_name="NordicMainMarkets",
            market="Main Market, Stockholm",
            page_size=2,
        )
        self.assertEqual([record["disclosureId"] for record in records], [1, 2, 3])
        self.assertIn("start=2", records[-1]["retrieval_url"])

    def test_fails_closed_when_count_is_not_reached(self) -> None:
        payloads = [
            {"results": {"item": [{"disclosureId": 1, "published": "2026-08-01 07:00:00"}]}, "count": 2},
            {"results": {"item": []}, "count": 2},
        ]

        def opener(request, timeout):
            return _Response(json.dumps(payloads.pop(0)).encode())

        with self.assertRaises(NasdaqSeDataError):
            NasdaqSeClient(opener=opener, requests_per_second=1000000).fetch_announcements(
                "Ericsson, Telefonab. L M",
                date(2026, 8, 1),
                date(2026, 8, 15),
                global_name="NordicMainMarkets",
                market="Main Market, Stockholm",
                page_size=1,
            )


class NasdaqSeConnectorTests(unittest.TestCase):
    def test_maps_official_record_and_raw_provenance(self) -> None:
        class Client:
            def fetch_share_directory(self):
                return [{
                    "symbol": "ERIC B",
                    "fullName": "Ericsson B",
                    # Stockholm also contains valid shares quoted in EUR;
                    # currency is an audit field, never a venue filter.
                    "currency": "EUR",
                    "listing_category": "MAIN_MARKET",
                }]

            def fetch_company_names(self, global_name, market):
                if global_name == "NordicMainMarkets":
                    return ["Ericsson, Telefonab. L M", "Epiroc Aktiebolag"]
                return []

            def fetch_announcements(self, company, start_date, end_date, **kwargs):
                return [{
                    "disclosureId": 1457412,
                    "categoryId": 69,
                    "headline": "Share buybacks in Ericsson",
                    "language": "en",
                    "cnsCategory": "Changes in company's own shares",
                    "messageUrl": "https://view.news.eu.nasdaq.com/view?id=abc",
                    "published": "2026-08-10 08:30:00",
                    "market": "Main Market, Stockholm",
                    "company": company,
                    "attachment": [],
                    "retrieval_url": "https://api.news.eu.nasdaq.com/news/query.action?...",
                }]

        items = NasdaqSeFilingsConnector(client=Client()).collect(
            CollectionRequest(
                tickers=("ERIC-B",),
                start_date=date(2026, 8, 1),
                end_date=date(2026, 8, 15),
                markets={"ERIC-B": "se"},
            )
        )
        self.assertEqual(len(items), 1)
        item = items[0]
        self.assertEqual(item.source, "nasdaq_se_filings")
        self.assertEqual(item.external_id, "1457412:en")
        self.assertEqual(item.market, "se")
        self.assertEqual(item.raw_metadata["provenance_schema_version"], 1)
        self.assertEqual(item.raw_metadata["official_source_id"], "1457412")
        self.assertEqual(item.raw_metadata["raw_payload"]["company"], "Ericsson, Telefonab. L M")


if __name__ == "__main__":
    unittest.main()
