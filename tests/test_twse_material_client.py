import json
from datetime import date, datetime, timezone
from pathlib import Path
import unittest
from urllib.error import HTTPError

from investment_monitor import (
    TwseMaterialClient,
    TwseMaterialDataError,
    TwseMaterialRequestError,
)
from investment_monitor.sources.twse_material.client import _parse_records


FIXTURES = Path(__file__).parent / "fixtures" / "twse_material"


class FakeResponse:
    def __init__(self, payload: bytes) -> None:
        self._body = payload

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return None

    def read(self) -> bytes:
        return self._body


class FakeOpener:
    def __init__(self, payload: bytes = None, error=None) -> None:
        self.payload = payload or (FIXTURES / "t187ap04_L.json").read_bytes()
        self.error = error
        self.calls: list = []

    def __call__(self, request, timeout=None):
        self.calls.append(request.full_url)
        if self.error is not None:
            raise self.error
        return FakeResponse(self.payload)


class TwseMaterialClientTests(unittest.TestCase):
    def make_client(self, opener, **kwargs) -> TwseMaterialClient:
        return TwseMaterialClient(
            opener=opener,
            requests_per_second=1000,
            **kwargs,
        )

    def test_parses_real_key_records(self) -> None:
        opener = FakeOpener()
        client = self.make_client(opener)

        records = client.fetch_material()

        self.assertEqual(len(records), 4)
        first = next(record for record in records if record["ticker"] == "1721")
        self.assertEqual(first["title"], "公告本公司名稱由「三晃股份有限公司」更名為「國慶科技股份有限公司」")
        self.assertEqual(first["calendar_date"], "2026-08-05")
        self.assertEqual(
            first["published_at"],
            datetime(2026, 8, 4, 23, 0, 4, tzinfo=timezone.utc),
        )
        self.assertFalse(first["date_only"])
        self.assertEqual(first["table_date"], "2026-08-06")
        self.assertEqual(first["clause"], "第51款")
        self.assertEqual(first["event_date"], "2026-06-29")
        self.assertIn("事實發生日", first["raw"])

    def test_date_only_record_uses_market_noon_and_calendar_date(self) -> None:
        records = _parse_records(
            json.loads(
                (FIXTURES / "t187ap04_L.json").read_text(encoding="utf-8")
            ),
            api_url="https://example.test/t187ap04_L",
        )
        date_only = next(
            record for record in records if record["ticker"] == "0050"
        )

        self.assertTrue(date_only["date_only"])
        self.assertEqual(date_only["calendar_date"], "2026-08-05")
        self.assertEqual(
            date_only["published_at"],
            datetime(2026, 8, 5, 4, 0, tzinfo=timezone.utc),
        )

    def test_external_id_is_stable(self) -> None:
        payload = (FIXTURES / "t187ap04_L.json").read_bytes()
        first = _parse_records(
            json.loads(payload),
            api_url="https://example.test/t187ap04_L",
        )[1]
        second = _parse_records(
            json.loads(payload),
            api_url="https://example.test/t187ap04_L",
        )[1]

        self.assertEqual(first["external_id"], second["external_id"])
        self.assertEqual(len(first["external_id"]), 40)

    def test_same_table_day_is_cached_without_extra_request(self) -> None:
        opener = FakeOpener()
        client = self.make_client(opener)

        client.fetch_material()
        client.fetch_material()

        self.assertEqual(len(opener.calls), 1)

    def test_invalid_json_raises_data_error(self) -> None:
        client = self.make_client(FakeOpener(payload=b"<html>not json</html>"))

        with self.assertRaises(TwseMaterialDataError):
            client.fetch_material()

    def test_http_error_raises_request_error(self) -> None:
        client = self.make_client(
            FakeOpener(
                error=HTTPError(
                    "https://example.test",
                    404,
                    "not found",
                    {},
                    None,
                )
            )
        )

        with self.assertRaises(TwseMaterialRequestError):
            client.fetch_material()


if __name__ == "__main__":
    unittest.main()
