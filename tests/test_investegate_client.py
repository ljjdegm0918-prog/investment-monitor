from datetime import date, datetime, timezone
from pathlib import Path
import unittest

from investment_monitor import (
    InvestegateDataError,
)


FIXTURES = Path(__file__).parent / "fixtures" / "investegate"


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


class InvestegateClientTests(unittest.TestCase):
    def test_parses_announcements_and_filters_dates(self) -> None:
        from investment_monitor.sources.investegate.client import (
            InvestegateClient,
            _parse_announcements,
        )

        html = (FIXTURES / "announcements.html").read_text(encoding="utf-8")
        records = _parse_announcements(
            html,
            base_url="https://www.investegate.co.uk",
            start_date=date(2026, 8, 1),
            end_date=date(2026, 8, 5),
        )

        self.assertEqual(len(records), 2)
        first = records[0]
        self.assertEqual(first["rns_id"], "9707019")
        self.assertEqual(first["title"], "Director/PDMR Shareholding")
        self.assertIn("/9707019", first["url"])
        # 05 Aug 2026 04:18 PM London (BST) = 15:18 UTC.
        self.assertEqual(
            first["published"],
            datetime(2026, 8, 5, 15, 18, tzinfo=timezone.utc),
        )
        self.assertEqual(records[1]["rns_id"], "9704388")

        opener = FakeOpener((FIXTURES / "announcements.html").read_bytes())
        client = InvestegateClient(opener=opener, requests_per_second=1000)
        fetched = client.fetch_announcements(
            "vod",
            date(2026, 8, 1),
            date(2026, 8, 5),
        )
        self.assertEqual(len(fetched), 2)
        self.assertIn("/company/VOD", opener.requested[0])

    def test_empty_table_returns_empty_list(self) -> None:
        from investment_monitor.sources.investegate.client import (
            _parse_announcements,
        )

        html = (FIXTURES / "empty.html").read_text(encoding="utf-8")
        records = _parse_announcements(
            html,
            base_url="https://www.investegate.co.uk",
            start_date=date(2026, 8, 1),
            end_date=date(2026, 8, 5),
        )

        self.assertEqual(records, [])

    def test_missing_table_raises_data_error(self) -> None:
        from investment_monitor.sources.investegate.client import (
            _parse_announcements,
        )

        with self.assertRaises(InvestegateDataError):
            _parse_announcements(
                "<html><body>blocked</body></html>",
                base_url="https://www.investegate.co.uk",
                start_date=date(2026, 8, 1),
                end_date=date(2026, 8, 5),
            )


if __name__ == "__main__":
    unittest.main()
