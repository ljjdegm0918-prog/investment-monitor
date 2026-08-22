import json
import unittest
from datetime import date

from investment_monitor.sources.bse_hu_announcements import BseHuClient, BseHuDataError


def _fragment(identifier: int, day: str, title: str = "Annual report") -> str:
    return (
        f'<a href="/site/newkib/en/{identifier}_{identifier}">'
        '<h2 class="issuer">OTP Bank Nyrt.</h2>'
        f'<span class="list-date">{day}</span>'
        f'<div class="title">{title}</div>'
        '</a>'
    )


class _Response:
    def __init__(self, body: str) -> None:
        self._body = body.encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return None

    def read(self) -> bytes:
        return self._body


class _Opener:
    def __init__(self, bodies):
        self.bodies = list(bodies)
        self.requests = []

    def open(self, request, timeout):
        self.requests.append(request)
        return _Response(self.bodies.pop(0))


def _initial(result) -> str:
    return (
        '<meta name="_csrf" content="token-123">'
        f'<script>var result = {json.dumps(result)}; '
        'var getPageUrl = "/issuers_news/rsp/rigetPage";</script>'
    )


class BseHuClientTests(unittest.TestCase):
    def test_uses_session_csrf_pagination_and_stops_at_start_boundary(self):
        first = {"pageCount": 3, "items": [{"data": _fragment(3, "17 Aug 2026. 09:30")}]}
        second = {"pageCount": 3, "items": [{"data": _fragment(2, "30 Jul 2026. 10:00")}]}
        opener = _Opener([_initial(first), json.dumps(second)])
        client = BseHuClient(opener=opener, max_pages=10)

        records = list(client.fetch(date(2026, 8, 1), date(2026, 8, 17)))

        self.assertEqual([record["external_id"] for record in records], ["bse-hu:3"])
        self.assertEqual(client.last_pages_read, 2)
        self.assertFalse(client.last_fetch_truncated)
        self.assertEqual(opener.requests[1].data, b"2")
        self.assertIn("_csrf=token-123", opener.requests[1].full_url)
        self.assertEqual(opener.requests[1].get_header("X-security"), "token-123")

    def test_marks_bounded_archive_as_truncated_at_page_limit(self):
        first = {"pageCount": 2, "items": [{"data": _fragment(3, "17 Aug 2026. 09:30")}]}
        client = BseHuClient(opener=_Opener([_initial(first)]), max_pages=1)

        list(client.fetch(date(2020, 1, 1), date(2026, 8, 17)))

        self.assertTrue(client.last_fetch_truncated)

    def test_missing_csrf_fails_closed(self):
        result = {"pageCount": 1, "items": []}
        client = BseHuClient(opener=_Opener([f'<script>var result = {json.dumps(result)}; var getPageUrl = "/x";</script>']))
        with self.assertRaises(BseHuDataError):
            list(client.fetch(date(2026, 8, 1), date(2026, 8, 17)))

    def test_overlapping_page_fails_closed(self):
        first = {"pageCount": 2, "items": [{"data": _fragment(3, "17 Aug 2026. 09:30")}]}
        second = {
            "pageCount": 2,
            "items": [
                {"data": _fragment(3, "17 Aug 2026. 09:30")},
                {"data": _fragment(2, "16 Aug 2026. 09:30")},
            ],
        }
        client = BseHuClient(
            opener=_Opener([_initial(first), json.dumps(second)]), max_pages=2
        )
        with self.assertRaisesRegex(BseHuDataError, "overlapped"):
            list(client.fetch(date(2026, 8, 1), date(2026, 8, 17)))


if __name__ == "__main__":
    unittest.main()
