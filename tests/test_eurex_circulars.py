from __future__ import annotations

import io
import unittest
from datetime import date

from investment_monitor.models import CollectionRequest
from investment_monitor.sources.eurex_circulars import EurexCircularsClient, EurexCircularsConnector


PAGE_ONE = b"""
<div class='hits-sl-content-container'>
 <a class='teasable-search-result-link' href='/ex-en/find/circulars/circular-5425142'>
  <p class='search-result-date'>Release date: Aug 12, 2026</p>
  <h2 class='search-result-tagline'>Circulars | Pricing | Eurex</h2>
  <h1 class='search-result-description'>052/2026: Test circular</h1>
 </a>
</div>
<button class='pagination-element pagination-button-next' data-js-search-link='/page-two'></button>
"""
PAGE_TWO = b"""
<div class='hits-sl-content-container'>
 <a class='teasable-search-result-link' href='/ex-en/find/circulars/circular-5300000'>
  <p class='search-result-date'>Release date: Jul 01, 2026</p>
  <h2 class='search-result-tagline'>Circulars | Rules | Eurex</h2>
  <h1 class='search-result-description'>Older circular</h1>
 </a>
</div>
"""


class _Response(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


class EurexCircularsTests(unittest.TestCase):
    def test_follows_official_next_link_and_stops_past_window(self) -> None:
        pages = [PAGE_ONE, PAGE_TWO]
        calls = []

        def opener(request, timeout):
            calls.append(request.full_url)
            return _Response(pages.pop(0))

        records = EurexCircularsClient(opener=opener).fetch(
            date(2026, 8, 1), date(2026, 8, 15)
        )
        self.assertEqual([record["external_id"] for record in records], ["5425142"])
        self.assertEqual(calls[-1], "https://www.eurex.com/page-two")

    def test_connector_is_source_wide_and_preserves_raw_result(self) -> None:
        class Client:
            def fetch(self, start_date, end_date):
                return [{
                    "external_id": "5425142",
                    "date": date(2026, 8, 12),
                    "published_at_raw": "Aug 12, 2026",
                    "tagline": "Circulars | Pricing | Eurex",
                    "title": "052/2026: Test circular",
                    "url": "https://www.eurex.com/ex-en/find/circulars/circular-5425142",
                    "retrieval_url": "https://www.eurex.com/ex-en/find/circulars/1720!search",
                    "raw_payload": {"title": "052/2026: Test circular"},
                }]

        items = EurexCircularsConnector(client=Client()).collect(
            CollectionRequest(
                tickers=("FDAX", "FESX"),
                start_date=date(2026, 8, 1),
                end_date=date(2026, 8, 15),
                markets={"FDAX": "eux", "FESX": "eux"},
            )
        )
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0].tickers, ("FDAX", "FESX"))
        self.assertEqual(items[0].raw_metadata["official_source_id"], "5425142")
        self.assertEqual(items[0].raw_metadata["raw_payload"]["title"], "052/2026: Test circular")


if __name__ == "__main__":
    unittest.main()
