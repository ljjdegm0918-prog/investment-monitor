"""Contract tests for the public Oslo Børs NewsWeb API."""

from datetime import date
import json
from pathlib import Path
from typing import Any, Mapping, Optional, Tuple
import unittest
from unittest.mock import patch

from investment_monitor.sources._public_disclosure import PublicDisclosureError
from investment_monitor.sources.no_pt_disclosures import NEWSWEB_ATTACHMENT_API, NewswebClient


FIXTURES = Path(__file__).parent / "fixtures" / "newsweb_no"


def fixture(name: str) -> Any:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


class NewswebClientTests(unittest.TestCase):
    def test_detail_supplies_body_attachments_corrections_and_canonical_page(self) -> None:
        listing = fixture("list_message.json")
        detail = fixture("detail_message.json")
        detail_calls = []

        def fake_fetch(
            url: str,
            *,
            payload: Optional[Mapping[str, Any]] = None,
            headers: Optional[Mapping[str, str]] = None,
        ) -> Tuple[Any, Mapping[str, str]]:
            if "/list?" in url:
                # Repeat the same filing for two markets to assert de-duplication.
                rows = [listing] if "market=XOSL" in url or "market=XOAX" in url else []
                return {"data": {"messages": rows, "overflow": False}}, {}
            detail_calls.append(url)
            return {"data": {"message": detail}}, {}

        with patch("investment_monitor.sources.no_pt_disclosures.fetch_json", fake_fetch):
            rows = list(NewswebClient().fetch(date(2026, 8, 21), date(2026, 8, 21)))

        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertEqual(len(detail_calls), 1)
        self.assertEqual(row["external_id"], "newsweb:680459")
        self.assertEqual(row["url"], "https://newsweb.oslobors.no/message/680459")
        self.assertEqual(row["summary"], "See ESMA form attached.")
        self.assertEqual(row["attachments"], [
            NEWSWEB_ATTACHMENT_API + "?messageId=680459&attachmentId=331697"
        ])
        self.assertIn("correctionForMessageId=670000", row["revision_semantics"])
        self.assertIn("message?messageId=680459", row["retrieval_url"])

    def test_overflow_splits_date_window_and_single_day_fails_closed(self) -> None:
        client = NewswebClient()
        calls = []

        def split_fetch(
            url: str,
            *,
            payload: Optional[Mapping[str, Any]] = None,
            headers: Optional[Mapping[str, str]] = None,
        ) -> Tuple[Any, Mapping[str, str]]:
            calls.append(url)
            if "fromDate=2026-08-01&toDate=2026-08-03" in url:
                return {"data": {"messages": [], "overflow": True}}, {}
            return {"data": {"messages": [], "overflow": False}}, {}

        with patch("investment_monitor.sources.no_pt_disclosures.fetch_json", split_fetch):
            self.assertEqual(client._fetch_window("XOSL", date(2026, 8, 1), date(2026, 8, 3)), [])
        self.assertEqual(len(calls), 3)

        def day_overflow(
            url: str,
            *,
            payload: Optional[Mapping[str, Any]] = None,
            headers: Optional[Mapping[str, str]] = None,
        ) -> Tuple[Any, Mapping[str, str]]:
            return {"data": {"messages": [], "overflow": True}}, {}

        with patch("investment_monitor.sources.no_pt_disclosures.fetch_json", day_overflow):
            with self.assertRaisesRegex(PublicDisclosureError, "overflow"):
                client._fetch_window("XOSL", date(2026, 8, 1), date(2026, 8, 1))

    def test_rejects_detail_attachment_count_mismatch(self) -> None:
        listing = fixture("list_message.json")
        detail = fixture("detail_message.json")
        detail["attachments"] = []

        def fake_fetch(
            url: str,
            *,
            payload: Optional[Mapping[str, Any]] = None,
            headers: Optional[Mapping[str, str]] = None,
        ) -> Tuple[Any, Mapping[str, str]]:
            if "/list?" in url:
                rows = [listing] if "market=XOSL" in url else []
                return {"data": {"messages": rows, "overflow": False}}, {}
            return {"data": {"message": detail}}, {}

        with patch("investment_monitor.sources.no_pt_disclosures.fetch_json", fake_fetch):
            with self.assertRaisesRegex(PublicDisclosureError, "attachment list"):
                list(NewswebClient().fetch(date(2026, 8, 21), date(2026, 8, 21)))


if __name__ == "__main__":
    unittest.main()
