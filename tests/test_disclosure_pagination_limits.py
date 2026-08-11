"""Shared truncation-boundary tests for the four EQS market clients."""

from datetime import date
import json
import unittest

from investment_monitor.sources.eqs_ch import EqsChClient, EqsChDataError
from investment_monitor.sources.eqs_dgap import EqsDgapClient, EqsDgapDataError
from investment_monitor.sources.eqs_it import EqsItClient, EqsItDataError
from investment_monitor.sources.eqs_nl import EqsNlClient, EqsNlDataError


class FakeResponse:
    def __init__(self, body: bytes) -> None:
        self._body = body

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return None

    def read(self) -> bytes:
        return self._body


class ScriptedOpener:
    def __init__(self, payloads) -> None:
        self.payloads = list(payloads)
        self.requested = []

    def __call__(self, request, timeout=None):
        self.requested.append(request.full_url)
        if not self.payloads:
            raise AssertionError(f"unexpected extra request: {request.full_url}")
        return FakeResponse(json.dumps(self.payloads.pop(0)).encode("utf-8"))


def eqs_records(isin: str, count: int, *, prefix: str = "page"):
    return [
        {
            "id": f"{prefix}-{index}_en",
            "headline": f"Disclosure {prefix}-{index}",
            "category": "Ad hoc Release",
            "categoryCode": "ADHOC",
            "dateUtc": "2026-08-05 07:30:00",
            "companyName": "Fixture Issuer",
            "isin": isin,
        }
        for index in range(count)
    ]


class EqsPaginationLimitTests(unittest.TestCase):
    CASES = (
        (EqsDgapClient, EqsDgapDataError, "DE0007164600"),
        (EqsNlClient, EqsNlDataError, "NL0000235190"),
        (EqsItClient, EqsItDataError, "IT0005239360"),
        (EqsChClient, EqsChDataError, "CH0012032113"),
    )

    def test_full_limit_page_with_confirmed_next_page_raises(self) -> None:
        for client_class, error_class, isin in self.CASES:
            with self.subTest(client=client_class.__name__):
                opener = ScriptedOpener((
                    {"status": 200, "records": eqs_records(isin, 10)},
                    {"status": 200, "records": eqs_records(isin, 1, prefix="next")},
                ))
                client = client_class(opener=opener, requests_per_second=1000)

                with self.assertRaises(error_class):
                    client.fetch_by_isin(
                        isin,
                        date(2026, 8, 1),
                        date(2026, 8, 8),
                        max_pages=1,
                    )

                self.assertEqual(len(opener.requested), 2)
                self.assertIn("page=2", opener.requested[1])

    def test_full_final_page_with_empty_probe_is_not_truncation(self) -> None:
        for client_class, _, isin in self.CASES:
            with self.subTest(client=client_class.__name__):
                opener = ScriptedOpener((
                    {"status": 200, "records": eqs_records(isin, 10)},
                    {"status": 200, "records": []},
                ))
                client = client_class(opener=opener, requests_per_second=1000)

                records = client.fetch_by_isin(
                    isin,
                    date(2026, 8, 1),
                    date(2026, 8, 8),
                    max_pages=1,
                )

                self.assertEqual(len(records), 10)
                self.assertEqual(len(opener.requested), 2)


if __name__ == "__main__":
    unittest.main()
