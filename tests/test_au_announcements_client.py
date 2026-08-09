from datetime import date, datetime, timezone
from pathlib import Path
import unittest

from investment_monitor import (
    AsxAnnouncementsClient,
    AsxAnnouncementsDataError,
)


FIXTURES = Path(__file__).parent / "fixtures" / "au_announcements"


class FakeResponse:
    def __init__(self, body: bytes) -> None:
        self._body = body

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return None

    def read(self) -> bytes:
        return self._body


class FakeOpener:
    def __init__(self, body: bytes) -> None:
        self.body = body
        self.requested: list = []

    def __call__(self, request, timeout=None):
        self.requested.append(request.full_url)
        return FakeResponse(self.body)


class AsxAnnouncementsClientTests(unittest.TestCase):
    def test_parses_announcements_and_filters_dates(self) -> None:
        body = (FIXTURES / "bhp_announcements.json").read_bytes()
        opener = FakeOpener(body)
        client = AsxAnnouncementsClient(
            opener=opener,
            requests_per_second=1000,
        )

        records = client.fetch_announcements(
            "BHP",
            date(2026, 8, 1),
            date(2026, 8, 6),
        )

        self.assertEqual(len(records), 3)
        self.assertIn("companies/BHP/announcements", opener.requested[0])
        first = records[0]
        self.assertEqual(first["external_id"], "2924-03111504-3A697237")
        self.assertEqual(first["title"], "Quarterly Activities Report")
        self.assertEqual(first["announcement_type"], "QUARTERLY ACTIVITIES REPORT")
        self.assertTrue(first["is_price_sensitive"])
        self.assertEqual(
            first["published"],
            datetime(2026, 8, 5, 2, 30, tzinfo=timezone.utc),
        )
        self.assertEqual(
            first["url"],
            "https://asx.api.markitdigital.com/"
            "asx-research/1.0/companies/BHP/announcements",
        )

    def test_empty_items_returns_empty_list(self) -> None:
        body = b'{"data":{"items":[]}}'
        client = AsxAnnouncementsClient(
            opener=FakeOpener(body),
            requests_per_second=1000,
        )

        records = client.fetch_announcements(
            "BHP",
            date(2026, 8, 1),
            date(2026, 8, 6),
        )

        self.assertEqual(records, [])

    def test_malformed_json_raises_data_error(self) -> None:
        client = AsxAnnouncementsClient(
            opener=FakeOpener(b"<html>blocked</html>"),
            requests_per_second=1000,
        )

        with self.assertRaises(AsxAnnouncementsDataError):
            client.fetch_announcements(
                "BHP",
                date(2026, 8, 1),
                date(2026, 8, 6),
            )


if __name__ == "__main__":
    unittest.main()
