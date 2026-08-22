"""Offline contract tests for Euronext Lisbon's official exchange archive."""

from datetime import date
from pathlib import Path
import unittest

from investment_monitor.sources._public_disclosure import PublicDisclosureError
from investment_monitor.sources.no_pt_disclosures import (
    LISBON_ARCHIVE,
    EuronextLisbonClient,
    _lisbon_records,
)


FIXTURES = Path(__file__).parent / "fixtures" / "euronext_lisbon"


def fixture(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


class EuronextLisbonClientTests(unittest.TestCase):
    def test_uses_canonical_filtered_archive_and_reads_to_explicit_empty_page(self) -> None:
        pages = [fixture("archive_page_0.html"), fixture("archive_empty.html")]
        calls = []
        sleeps = []

        def fetcher(url: str):
            calls.append(url)
            return pages[len(calls) - 1], {}

        client = EuronextLisbonClient(
            fetcher=fetcher,
            sleeper=sleeps.append,
            request_interval=0.1,
        )
        rows = list(client.fetch(date(2026, 7, 6), date(2026, 7, 6)))

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["external_id"], "euronext-lisbon:12897490")
        self.assertEqual(rows[0]["document_type"], "Inside information")
        self.assertEqual(rows[0]["published_at"].tzinfo.key, "Europe/Lisbon")
        self.assertTrue(all(url.startswith(LISBON_ARCHIVE) for url in calls))
        self.assertIn("page=0", calls[0])
        self.assertIn("page=1", calls[1])
        self.assertEqual(sleeps, [0.1])

    def test_dropped_filters_and_changed_rows_fail_closed(self) -> None:
        empty = fixture("archive_empty.html").replace(
            '"field_company_pr_pub_datetime_start":"2026-07-06 00:00:00",', ""
        )
        client = EuronextLisbonClient(
            fetcher=lambda _url: (empty, {}), request_interval=0
        )
        with self.assertRaisesRegex(PublicDisclosureError, "retain.*date filters"):
            list(client.fetch(date(2026, 7, 6), date(2026, 7, 6)))

        changed = fixture("archive_page_0.html").replace(
            ' data-node-nid="12897490"', ""
        )
        with self.assertRaisesRegex(PublicDisclosureError, "changed structure"):
            _lisbon_records(changed, LISBON_ARCHIVE)

    def test_repeated_page_and_page_cap_fail_closed(self) -> None:
        page = fixture("archive_page_0.html")
        client = EuronextLisbonClient(
            fetcher=lambda _url: (page, {}), request_interval=0, max_pages=2
        )
        with self.assertRaisesRegex(PublicDisclosureError, "repeated"):
            list(client.fetch(date(2026, 7, 6), date(2026, 7, 6)))

        client = EuronextLisbonClient(
            fetcher=lambda _url: (page, {}), request_interval=0, max_pages=1
        )
        with self.assertRaisesRegex(PublicDisclosureError, "max_pages=1"):
            list(client.fetch(date(2026, 7, 6), date(2026, 7, 6)))

    def test_waf_page_is_not_a_valid_empty_result(self) -> None:
        text = (
            "2026-07-06 00:00:00 2026-07-06 23:59:59 "
            "<html><title>Access Denied</title></html>"
        )
        client = EuronextLisbonClient(
            fetcher=lambda _url: (text, {}), request_interval=0
        )
        with self.assertRaisesRegex(PublicDisclosureError, "WAF/login"):
            list(client.fetch(date(2026, 7, 6), date(2026, 7, 6)))

    def test_non_filing_press_release_is_excluded(self) -> None:
        press_release = fixture("archive_page_0.html").replace(
            "Inside information", "Commercial operations"
        )
        pages = iter((press_release, fixture("archive_empty.html")))
        client = EuronextLisbonClient(
            fetcher=lambda _url: (next(pages), {}), request_interval=0
        )
        self.assertEqual(
            list(client.fetch(date(2026, 7, 6), date(2026, 7, 6))), []
        )
        self.assertEqual(client.last_excluded_non_filings, 1)


if __name__ == "__main__":
    unittest.main()
