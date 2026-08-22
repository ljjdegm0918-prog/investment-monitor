"""Contract tests for the public MAYA company-report API."""

from datetime import date
import json
from pathlib import Path
from typing import Any, Mapping, Optional, Tuple
import unittest
from unittest.mock import patch

from investment_monitor.sources._public_disclosure import PublicDisclosureError
from investment_monitor.sources.maya_announcements import MayaClient, REPORTS_URL


FIXTURES = Path(__file__).parent / "fixtures" / "maya_announcements"


def fixture(name: str) -> Any:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


class MayaClientTests(unittest.TestCase):
    def test_paginates_against_total_and_prefers_pdf(self) -> None:
        autocomplete = fixture("autocomplete_teva.json")
        reports = fixture("company_reports.json")
        client = MayaClient()
        client.page_size = 1
        calls = []

        def fake_fetch(
            url: str,
            *,
            payload: Optional[Mapping[str, Any]] = None,
            headers: Optional[Mapping[str, str]] = None,
        ) -> Tuple[Any, Mapping[str, str]]:
            if "autocomplete" in url:
                return autocomplete, {}
            self.assertEqual(url, REPORTS_URL)
            assert payload is not None
            self.assertEqual(headers["Accept-Language"], "he-IL")
            calls.append(payload)
            offset = payload["offset"]
            return [reports[offset]], {"X-Total-Count": "2"}

        with patch("investment_monitor.sources.maya_announcements.fetch_json", fake_fetch):
            rows = list(client.fetch_for_tickers(("TEVA",), date(2026, 8, 1), date(2026, 8, 21)))

        self.assertEqual([call["offset"] for call in calls], [0, 1])
        self.assertEqual(rows[0]["external_id"], "maya:1764653")
        self.assertEqual(rows[0]["published_at"].tzinfo.key, "Asia/Jerusalem")
        self.assertTrue(rows[0]["url"].endswith("P1764653-00.pdf"))
        self.assertEqual(rows[0]["attachments"][1].split("/")[-1], "H1764653.htm")
        self.assertIn("correctives=1760000", rows[1]["revision_semantics"])

    def test_unresolved_ticker_does_not_discard_other_tickers(self) -> None:
        autocomplete = fixture("autocomplete_teva.json")
        reports = fixture("company_reports.json")

        def fake_fetch(
            url: str,
            *,
            payload: Optional[Mapping[str, Any]] = None,
            headers: Optional[Mapping[str, str]] = None,
        ) -> Tuple[Any, Mapping[str, str]]:
            if "autocomplete" in url:
                return ([] if "BAD" in url else autocomplete), {}
            return [reports[0]], {"x-total-count": "1"}

        client = MayaClient()
        with patch("investment_monitor.sources.maya_announcements.fetch_json", fake_fetch):
            rows = list(client.fetch_for_tickers(("BAD", "TEVA"), date(2026, 8, 1), date(2026, 8, 21)))

        self.assertEqual(len(rows), 1)
        self.assertEqual(client.last_ticker_errors, (("BAD", "MAYA company not found"),))

    def test_rejects_missing_total_header_and_missing_report_id(self) -> None:
        autocomplete = fixture("autocomplete_teva.json")
        report = fixture("company_reports.json")[0]

        def missing_total(
            url: str,
            *,
            payload: Optional[Mapping[str, Any]] = None,
            headers: Optional[Mapping[str, str]] = None,
        ) -> Tuple[Any, Mapping[str, str]]:
            return (autocomplete, {}) if "autocomplete" in url else ([report], {})

        with patch("investment_monitor.sources.maya_announcements.fetch_json", missing_total):
            with self.assertRaisesRegex(PublicDisclosureError, "x-total-count"):
                list(MayaClient().fetch_for_tickers(("TEVA",), date(2026, 8, 1), date(2026, 8, 21)))

    def test_repeated_report_id_fails_closed(self) -> None:
        autocomplete = fixture("autocomplete_teva.json")
        report = fixture("company_reports.json")[0]

        def repeated(
            url: str,
            *,
            payload: Optional[Mapping[str, Any]] = None,
            headers: Optional[Mapping[str, str]] = None,
        ) -> Tuple[Any, Mapping[str, str]]:
            if "autocomplete" in url:
                return autocomplete, {}
            return [report], {"x-total-count": "2"}

        client = MayaClient(request_interval=0)
        client.page_size = 1
        with patch("investment_monitor.sources.maya_announcements.fetch_json", repeated):
            with self.assertRaisesRegex(PublicDisclosureError, "repeated id"):
                list(client.fetch_for_tickers(("TEVA",), date(2026, 8, 1), date(2026, 8, 21)))

        malformed = dict(report)
        malformed["id"] = None

        def missing_id(
            url: str,
            *,
            payload: Optional[Mapping[str, Any]] = None,
            headers: Optional[Mapping[str, str]] = None,
        ) -> Tuple[Any, Mapping[str, str]]:
            return (autocomplete, {}) if "autocomplete" in url else ([malformed], {"x-total-count": "1"})

        with patch("investment_monitor.sources.maya_announcements.fetch_json", missing_id):
            with self.assertRaisesRegex(PublicDisclosureError, "missing id"):
                list(MayaClient().fetch_for_tickers(("TEVA",), date(2026, 8, 1), date(2026, 8, 21)))


if __name__ == "__main__":
    unittest.main()
