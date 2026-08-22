"""Offline durability tests for the public, partial BMV event bulletin."""

from datetime import date
from pathlib import Path
import unittest

from investment_monitor.models import CollectionRequest
from investment_monitor.sources._public_disclosure import PublicDisclosureError
from investment_monitor.sources.bmv_relevant_events import (
    FIRST_PAGE,
    PAGE_URL,
    BmvRelevantEventsClient,
    BmvRelevantEventsConnector,
)


FIXTURES = Path(__file__).parent / "fixtures" / "bmv_relevant_events"


def fixture(name):
    return (FIXTURES / name).read_text(encoding="utf-8")


class FixtureFetcher:
    def __init__(self, pages):
        self.pages = pages
        self.urls = []

    def __call__(self, url):
        self.urls.append(url)
        value = self.pages[url]
        if isinstance(value, list):
            value = value.pop(0)
        if isinstance(value, Exception):
            raise value
        return value, {}


class BmvRelevantEventsClientTests(unittest.TestCase):
    def test_filters_dates_preserves_native_id_and_attachments(self):
        fetcher = FixtureFetcher({
            FIRST_PAGE: fixture("page_1.html"),
            PAGE_URL.format(2): fixture("page_2_old.html"),
        })
        sleeps = []
        client = BmvRelevantEventsClient(
            fetcher=fetcher, sleeper=sleeps.append, page_delay=0.25,
        )

        rows = list(client.fetch(date(2026, 8, 2), date(2026, 8, 2)))

        self.assertEqual([row["external_id"] for row in rows], ["bmv-event:1001"])
        self.assertEqual(rows[0]["ticker"], "WALMEX")
        self.assertEqual(rows[0]["native_id"], "1001")
        self.assertEqual(rows[0]["attachments"], [
            "https://www.bmv.com.mx/docs-pub/eventore/eventore_1001_1.pdf",
        ])
        self.assertEqual(rows[0]["detail_url"], rows[0]["url"])
        self.assertEqual(rows[0]["retrieval_url"], FIRST_PAGE)
        self.assertEqual(rows[0]["published_timezone"], "America/Mexico_City")
        self.assertEqual(fetcher.urls, [FIRST_PAGE, PAGE_URL.format(2)])
        self.assertEqual(sleeps, [0.25])

    def test_zero_announcement_page_is_an_honest_empty_result(self):
        client = BmvRelevantEventsClient(
            fetcher=FixtureFetcher({FIRST_PAGE: fixture("zero.html")}),
            sleeper=lambda _: None,
        )
        self.assertEqual(list(client.fetch(date(2026, 8, 2), date(2026, 8, 2))), [])

    def test_missing_bulletin_structure_fails_closed(self):
        client = BmvRelevantEventsClient(
            fetcher=FixtureFetcher({FIRST_PAGE: "<html>upstream error</html>"}),
            sleeper=lambda _: None,
        )
        with self.assertRaisesRegex(PublicDisclosureError, "structure missing"):
            list(client.fetch(date(2026, 8, 2), date(2026, 8, 2)))

    def test_malformed_event_row_is_not_treated_as_an_empty_page(self):
        malformed = """
            <h1>Eventos Relevantes</h1><table><tr>
            <h2>Disclosure title</h2><strong>2026-08-02 09:30 AM</strong>
            <strong>WALMEX</strong></tr></table>
        """
        client = BmvRelevantEventsClient(
            fetcher=FixtureFetcher({FIRST_PAGE: malformed}), sleeper=lambda _: None,
        )
        with self.assertRaisesRegex(PublicDisclosureError, "markup changed"):
            list(client.fetch(date(2026, 8, 2), date(2026, 8, 2)))

    def test_retries_transport_failures_with_injected_backoff(self):
        sleeps = []
        client = BmvRelevantEventsClient(
            fetcher=FixtureFetcher({
                FIRST_PAGE: [OSError("temporary failure"), fixture("zero.html")],
            }),
            sleeper=sleeps.append,
            retry_delay=0.4,
        )
        self.assertEqual(list(client.fetch(date(2026, 8, 2), date(2026, 8, 2))), [])
        self.assertEqual(sleeps, [0.4])

    def test_duplicate_page_fails_closed(self):
        first = fixture("page_1.html")
        client = BmvRelevantEventsClient(
            fetcher=FixtureFetcher({FIRST_PAGE: first, PAGE_URL.format(2): first}),
            sleeper=lambda _: None,
        )
        with self.assertRaisesRegex(PublicDisclosureError, "repeated or overlapped"):
            list(client.fetch(date(2026, 7, 1), date(2026, 8, 3)))

    def test_hard_cap_fails_closed(self):
        client = BmvRelevantEventsClient(
            fetcher=FixtureFetcher({
                FIRST_PAGE: fixture("page_1.html"),
                PAGE_URL.format(2): fixture("page_2_old.html"),
            }),
            sleeper=lambda _: None, max_pages=2,
        )
        with self.assertRaisesRegex(PublicDisclosureError, "hard cap"):
            list(client.fetch(date(2026, 7, 1), date(2026, 8, 3)))

    def test_market_notices_are_not_returned_as_issuer_filings(self):
        client = BmvRelevantEventsClient(
            fetcher=FixtureFetcher({FIRST_PAGE: fixture("page_1.html")}),
            sleeper=lambda _: None,
        )
        rows = list(client.fetch(date(2026, 8, 3), date(2026, 8, 3)))
        self.assertEqual([row["ticker"] for row in rows], ["WALMEX"])
        self.assertEqual(rows[0]["classification_code"], "issuer_event")
        self.assertEqual(rows[0]["attachments"], [
            "https://www.bmv.com.mx/docs-pub/eventore/eventore_1003_1.pdf",
            "https://www.bmv.com.mx/docs-pub/eventore/eventore_1003_2.pdf",
        ])
        self.assertEqual(rows[0]["url"], rows[0]["attachments"][0])

    def test_unknown_issuer_is_not_matched_to_requested_identity(self):
        client = BmvRelevantEventsClient(
            fetcher=FixtureFetcher({FIRST_PAGE: fixture("page_1.html")}),
            sleeper=lambda _: None,
        )
        connector = BmvRelevantEventsConnector(
            client=client,
            universe={"OTHER": {"name": "Other issuer"}},
        )
        items = connector.collect(CollectionRequest(
            tickers=("OTHER",), start_date=date(2026, 8, 3), end_date=date(2026, 8, 3),
            markets={"OTHER": "mx"},
        ))
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0].tickers, ())
        self.assertEqual(items[0].raw_metadata["match_status"], "pending")
        self.assertEqual(connector.last_collection_status, "success")
        self.assertEqual(connector.coverage_level, "official")

    def test_ambiguous_row_is_retained_as_pending_not_an_issuer_filing(self):
        uncertain = """
            <h1>Eventos Relevantes</h1><table><tr>
            <h2>Unattributed announcement</h2><strong>2026-08-03 09:30 AM</strong>
            <strong> </strong><a href="/docs-pub/eventore/eventore_9001_1.pdf">
            Descargar PRINCIPAL</a></tr></table>
        """
        client = BmvRelevantEventsClient(
            fetcher=FixtureFetcher({
                FIRST_PAGE: uncertain,
                PAGE_URL.format(2): fixture("zero.html"),
            }),
            sleeper=lambda _: None,
        )
        rows = list(client.fetch(date(2026, 8, 3), date(2026, 8, 3)))
        self.assertEqual(rows[0]["classification_code"], "pending_matching")
        self.assertEqual(rows[0]["ticker"], "")
        self.assertEqual(client.pending_records, tuple(rows))


if __name__ == "__main__":
    unittest.main()
