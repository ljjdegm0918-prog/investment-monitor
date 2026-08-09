import json
from datetime import date, datetime, timezone
from pathlib import Path
import unittest

from investment_monitor import (
    TpexMaterialClient,
    TpexMaterialDataError,
)
from investment_monitor.sources.tpex_material.client import _parse_records


FIXTURES = Path(__file__).parent / "fixtures" / "tpex_material"


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
        self.payload = payload or (FIXTURES / "t187ap04_O.json").read_bytes()
        self.error = error
        self.calls: list = []

    def __call__(self, request, timeout=None):
        self.calls.append(request.full_url)
        if self.error is not None:
            raise self.error
        return FakeResponse(self.payload)


class TpexMaterialClientTests(unittest.TestCase):
    def make_client(self, opener, **kwargs) -> TpexMaterialClient:
        return TpexMaterialClient(
            opener=opener,
            requests_per_second=1000,
            **kwargs,
        )

    def test_parses_mixed_key_records(self) -> None:
        client = self.make_client(FakeOpener())

        records = client.fetch_material()

        self.assertEqual(len(records), 3)
        first = next(r for r in records if r["ticker"] == "4530")
        self.assertEqual(
            first["title"],
            "公告本公司名稱由「宏易創新國際股份有限公司」更名為「天意能創股份有限公司」",
        )
        self.assertEqual(first["calendar_date"], "2026-08-05")
        self.assertEqual(
            first["published_at"],
            datetime(2026, 8, 4, 23, 0, 4, tzinfo=timezone.utc),
        )
        self.assertFalse(first["date_only"])
        self.assertEqual(first["table_date"], "2026-08-06")
        self.assertEqual(first["clause"], "第53款")
        self.assertEqual(first["event_date"], "2026-07-08")
        self.assertEqual(first["external_id"], _parse_records(
            json.loads(
                (FIXTURES / "t187ap04_O.json").read_text(encoding="utf-8")
            ),
            api_url="x",
        )[0]["external_id"])

    def test_same_table_day_is_cached_without_extra_request(self) -> None:
        opener = FakeOpener()
        client = self.make_client(opener)

        client.fetch_material()
        client.fetch_material()

        self.assertEqual(len(opener.calls), 1)

    def test_invalid_json_raises_data_error(self) -> None:
        client = self.make_client(FakeOpener(payload=b"<html>not json</html>"))

        with self.assertRaises(TpexMaterialDataError):
            client.fetch_material()


if __name__ == "__main__":
    unittest.main()
