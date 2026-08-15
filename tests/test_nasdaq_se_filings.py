from __future__ import annotations

import io
import json
import unittest
from datetime import date

from investment_monitor.models import CollectionRequest
from investment_monitor.sources.nasdaq_se import (
    NasdaqSeClient,
    NasdaqSeDataError,
    NasdaqSeFilingsConnector,
)


class _Response(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


class NasdaqSeClientTests(unittest.TestCase):
    def test_share_directory_combines_main_and_first_north(self) -> None:
        payloads = [
            {"data": {"instrumentListing": {"rows": [{"symbol": "ERIC B"}]}}},
            {"data": {"instrumentListing": {"rows": [{"symbol": "AAA"}]}}},
        ]

        def opener(request, timeout):
            return _Response(json.dumps(payloads.pop(0)).encode())

        rows = NasdaqSeClient(opener=opener, requests_per_second=1000000).fetch_share_directory()
        self.assertEqual([row["symbol"] for row in rows], ["ERIC B", "AAA"])
        self.assertEqual(
            [row["listing_category"] for row in rows],
            ["MAIN_MARKET", "FIRST_NORTH"],
        )

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
                    "currency": "SEK",
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
