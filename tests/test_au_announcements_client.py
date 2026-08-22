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
    def __init__(self, bodies: dict[str, bytes]) -> None:
        self.bodies = bodies
        self.requested: list[str] = []

    def __call__(self, request, timeout=None):
        url = request.full_url
        self.requested.append(url)
        for fragment, body in self.bodies.items():
            if fragment in url:
                return FakeResponse(body)
        raise AssertionError(f"No fake response for {url}")


class AsxAnnouncementsClientTests(unittest.TestCase):
    def archive_opener(self) -> FakeOpener:
        return FakeOpener(
            {
                "year=2026": (FIXTURES / "bhp_2026_archive.html").read_bytes(),
                "year=2025": (FIXTURES / "bhp_2025_archive.html").read_bytes(),
            }
        )

    def test_parses_official_archive_and_filters_dates(self) -> None:
        opener = self.archive_opener()
        client = AsxAnnouncementsClient(
            opener=opener,
            requests_per_second=1000,
        )

        records = client.fetch_announcements(
            "BHP",
            date(2026, 7, 1),
            date(2026, 7, 31),
        )

        self.assertEqual(len(records), 2)
        self.assertIn("asxCode=BHP", opener.requested[0])
        self.assertIn("timeframe=Y", opener.requested[0])
        self.assertIn("year=2026", opener.requested[0])
        first = records[0]
        self.assertEqual(first["external_id"], "03115448")
        self.assertEqual(first["title"], "Quarterly Activities Report")
        self.assertEqual(first["page_count"], 25)
        self.assertEqual(first["file_size"], "655.2KB")
        self.assertTrue(first["is_price_sensitive"])
        self.assertEqual(
            first["published"].astimezone(timezone.utc),
            datetime(2026, 7, 15, 22, 39, tzinfo=timezone.utc),
        )
        self.assertEqual(
            first["url"],
            "https://www.asx.com.au/asx/v2/statistics/"
            "displayAnnouncement.do?display=pdf&idsId=03115448",
        )

    def test_cross_year_window_requests_each_archive_year(self) -> None:
        opener = self.archive_opener()
        client = AsxAnnouncementsClient(
            opener=opener,
            requests_per_second=1000,
        )

        records = client.fetch_announcements(
            "BHP",
            date(2025, 12, 30),
            date(2026, 1, 2),
        )

        self.assertEqual([record["external_id"] for record in records], ["02999999"])
        self.assertEqual(len(opener.requested), 2)
        self.assertTrue(any("year=2025" in url for url in opener.requested))
        self.assertTrue(any("year=2026" in url for url in opener.requested))

    def test_empty_archive_results_returns_empty_list(self) -> None:
        body = b"<html><h1>Announcements released as BHP</h1>No announcements were released</html>"
        client = AsxAnnouncementsClient(
            opener=FakeOpener({"year=2026": body}),
            requests_per_second=1000,
        )

        records = client.fetch_announcements(
            "BHP",
            date(2026, 8, 1),
            date(2026, 8, 6),
        )

        self.assertEqual(records, [])

    def test_non_archive_html_raises_data_error(self) -> None:
        client = AsxAnnouncementsClient(
            opener=FakeOpener({"year=2026": b"<html>blocked</html>"}),
            requests_per_second=1000,
        )

        with self.assertRaises(AsxAnnouncementsDataError):
            client.fetch_announcements(
                "BHP",
                date(2026, 8, 1),
                date(2026, 8, 6),
            )

    def test_unparseable_archive_result_row_fails_closed(self) -> None:
        body = b"""<html><h1>Announcements released as BHP</h1><table>
        <tr><td>06/08/2026 8:30 am</td><td></td><td>Missing official link</td></tr>
        </table></html>"""
        client = AsxAnnouncementsClient(
            opener=FakeOpener({"year=2026": body}),
            requests_per_second=1000,
        )
        with self.assertRaises(AsxAnnouncementsDataError):
            client.fetch_announcements(
                "BHP", date(2026, 8, 1), date(2026, 8, 6)
            )


if __name__ == "__main__":
    unittest.main()
