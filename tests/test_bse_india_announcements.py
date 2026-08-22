from datetime import date
from pathlib import Path
import unittest

from investment_monitor.models import CollectionRequest
from investment_monitor.dedupe import annotate_feed_items
from investment_monitor.sources.bse_india_announcements import (
    BseIndiaAnnouncementsClient,
    BseIndiaAnnouncementsConnector,
    BseIndiaAnnouncementsDataError,
    BseIndiaAnnouncementsRequestError,
)


FIXTURES = Path(__file__).parent / "fixtures" / "bse_india_announcements"


class FakeResponse:
    def __init__(self, body: bytes) -> None:
        self._body = body

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return None

    def read(self) -> bytes:
        return self._body


class FixtureOpener:
    def __init__(self) -> None:
        self.urls = []

    def __call__(self, request, timeout=None):
        url = request.full_url
        self.urls.append(url)
        if "ListofScripData" in url:
            return FakeResponse((FIXTURES / "securities.json").read_bytes())
        if "pageno=1" in url:
            return FakeResponse((FIXTURES / "reliance_page_1.json").read_bytes())
        if "pageno=2" in url:
            return FakeResponse((FIXTURES / "reliance_page_2.json").read_bytes())
        raise AssertionError(f"unexpected BSE URL: {url}")


class BseIndiaAnnouncementsTests(unittest.TestCase):
    def make_connector(self):
        opener = FixtureOpener()
        return (
            BseIndiaAnnouncementsConnector(
                BseIndiaAnnouncementsClient(
                    opener=opener,
                    requests_per_second=1000,
                )
            ),
            opener,
        )

    @staticmethod
    def request(tickers, markets):
        return CollectionRequest(
            tickers=tickers,
            start_date=date(2026, 8, 15),
            end_date=date(2026, 8, 15),
            markets=markets,
        )

    def test_resolves_bse_symbol_paginates_and_maps_official_attachment(self):
        connector, opener = self.make_connector()

        items = connector.collect(self.request(("RELIANCE.BO",), {"RELIANCE.BO": "in"}))

        self.assertEqual(len(items), 2)
        self.assertEqual(items[0].source, "bse_india_announcements")
        self.assertEqual(items[0].external_id, "bse-india:548da0e0-e4c7-4cce-8ad7-a2af8d154f54")
        self.assertEqual(items[0].tickers, ("RELIANCE",))
        self.assertEqual(items[0].market, "in")
        self.assertEqual(items[0].published_at.isoformat(), "2026-08-15T18:29:12.827000+00:00")
        self.assertEqual(
            items[0].url,
            "https://www.bseindia.com/xml-data/corpfiling/AttachLive/"
            "548da0e0-e4c7-4cce-8ad7-a2af8d154f54.pdf",
        )
        self.assertEqual(items[0].raw_metadata["isin"], "INE002A01018")
        self.assertEqual(items[1].url, "https://www.bseindia.com/corporates/ann.html")
        self.assertEqual(items[0].raw_metadata["raw_payload_format"], "json")
        self.assertEqual(connector.last_collection_status, "success")
        self.assertEqual(sum("pageno=" in url for url in opener.urls), 2)
        self.assertEqual(connector.last_errors, ())

    def test_resolves_scrip_code_and_isin(self):
        connector, _ = self.make_connector()
        for ticker in ("500325", "INE002A01018"):
            with self.subTest(ticker=ticker):
                items = connector.collect(self.request((ticker,), {ticker: "in"}))
                self.assertEqual([item.tickers for item in items], [("RELIANCE",), ("RELIANCE",)])

    def test_non_india_market_has_zero_http(self):
        connector, opener = self.make_connector()

        self.assertEqual(
            connector.collect(self.request(("AAPL",), {"AAPL": "us"})), []
        )
        self.assertEqual(opener.urls, [])

    def test_unmapped_single_ticker_fails_closed(self):
        connector, _ = self.make_connector()

        with self.assertRaises(BseIndiaAnnouncementsRequestError):
            connector.collect(self.request(("MISSING.BO",), {"MISSING.BO": "in"}))
        self.assertEqual(connector.last_errors[0][0], "MISSING.BO")

    def test_client_rejects_early_pagination_termination(self):
        class EmptySecondPageOpener(FixtureOpener):
            def __call__(self, request, timeout=None):
                if "pageno=2" in request.full_url:
                    return FakeResponse(b'{"Table": [], "Table1": [{"ROWCNT": 3}]}')
                return super().__call__(request, timeout)

        client = BseIndiaAnnouncementsClient(
            opener=EmptySecondPageOpener(), requests_per_second=1000
        )
        with self.assertRaises(BseIndiaAnnouncementsDataError):
            client.fetch_announcements("500325", date(2026, 8, 15), date(2026, 8, 15))

    def test_client_rejects_duplicate_news_id_across_pages(self):
        class DuplicateSecondPageOpener(FixtureOpener):
            def __call__(self, request, timeout=None):
                if "pageno=2" in request.full_url:
                    return FakeResponse((FIXTURES / "reliance_page_1.json").read_bytes())
                return super().__call__(request, timeout)

        client = BseIndiaAnnouncementsClient(
            opener=DuplicateSecondPageOpener(), requests_per_second=1000
        )
        with self.assertRaises(BseIndiaAnnouncementsDataError):
            client.fetch_announcements("500325", date(2026, 8, 15), date(2026, 8, 15))

    def test_attachment_paths_are_rejected(self):
        client = BseIndiaAnnouncementsClient(requests_per_second=1000)
        with self.assertRaises(BseIndiaAnnouncementsDataError):
            client.attachment_url("../../not-a-bse-file.pdf")

    def test_nse_bse_same_announcement_is_annotated_but_both_rows_remain(self):
        base = {
            "source_type": "regulatory_filing",
            "market": "in",
            "ticker": "RELIANCE",
            "title": "Board meeting outcome",
            "published_at": "2026-08-15T10:00:00+05:30",
        }
        rows = annotate_feed_items([
            {**base, "source": "nse_announcements", "external_id": "nse:1"},
            {**base, "source": "bse_india_announcements", "external_id": "bse-india:2"},
        ])
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]["also_seen_on"], ["bse_india_announcements"])
        self.assertEqual(rows[1]["also_seen_on"], ["nse_announcements"])


if __name__ == "__main__":
    unittest.main()
