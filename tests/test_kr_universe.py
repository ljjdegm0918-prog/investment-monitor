import io
import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch
from urllib.parse import parse_qs
import zipfile

from investment_monitor import (
    KrUniverseError,
    SQLiteInformationRepository,
    WebRepository,
    kr_universe_name_map,
    load_kr_universe,
    refresh_kr_universe,
)


def make_zip(rows):
    xml_parts = ['<?xml version="1.0" encoding="UTF-8"?><result>']
    for corp_code, corp_name, stock_code in rows:
        xml_parts.append(
            "<list>"
            f"<corp_code>{corp_code}</corp_code>"
            f"<corp_name>{corp_name}</corp_name>"
            f"<stock_code>{stock_code}</stock_code>"
            "<modify_date>20260801</modify_date>"
            "</list>"
        )
    xml_parts.append("</result>")
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr(
            "CORPCODE.xml",
            "".join(xml_parts).encode("utf-8"),
        )
    return buffer.getvalue()


class FakeDartClient:
    def __init__(self, zip_bytes) -> None:
        self.zip_bytes = zip_bytes
        self.calls: list = []

    def get_bytes(self, path: str, parameters):
        self.calls.append((path, parameters))
        return self.zip_bytes


class KrUniverseTests(unittest.TestCase):
    def test_refresh_dart_corpcode_writes_and_loads_cache(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            cache_path = Path(temporary_directory) / "kr_universe.json"
            client = FakeDartClient(
                make_zip(
                    [
                        ("00593000", "삼성전자", "005930"),
                        ("00027000", "기아", "000270"),
                        ("00000001", "미상장법인", ""),
                    ]
                )
            )

            with patch.dict(
                os.environ,
                {
                    "DART_CORP_CODE_CACHE_PATH": str(
                        Path(temporary_directory) / "dart_corp.json"
                    )
                },
                clear=False,
            ):
                payload = refresh_kr_universe(
                    path=cache_path,
                    source="dart_corpcode",
                    dart_client=client,
                )
                loaded = load_kr_universe(cache_path)

            self.assertEqual(payload["source"], "dart_corpcode")
            self.assertEqual(len(payload["items"]), 2)
            first = payload["items"][0]
            self.assertEqual(first["stock_code"], "000270")
            self.assertEqual(first["name"], "기아")
            self.assertEqual(first["instrument_kind"], "equity")
            self.assertEqual(first["exchange"], "KRX")
            self.assertEqual(first["market_hint"], "KRX")
            self.assertEqual(loaded, payload)

    def test_refresh_without_dart_key_raises_graceful_error(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            with patch.dict(
                os.environ,
                {"DART_API_KEY": ""},
                clear=False,
            ):
                with self.assertRaises(KrUniverseError) as raised:
                    refresh_kr_universe(
                        path=Path(temporary_directory) / "kr_universe.json",
                        source="dart_corpcode",
                    )

            self.assertIn("dart_corpcode", str(raised.exception))

    def test_data_krx_adapter_parses_blocks(self) -> None:
        blocks = {
            "STK": [
                {
                    "ISU_SRT_CD": "005930",
                    "ISU_ABBRV": "삼성전자",
                    "MKT_NM": "KOSPI",
                }
            ],
            "KSQ": [],
            "ETF": [
                {
                    "ISU_SRT_CD": "069500",
                    "ISU_ABBRV": "KODEX 200",
                    "MKT_NM": "ETF",
                }
            ],
            "ETN": [
                {
                    "ISU_SRT_CD": "500001",
                    "ISU_ABBRV": "삼성 ETN 예시",
                    "MKT_NM": "ETN",
                }
            ],
        }

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
            def __init__(self) -> None:
                self.posted: list = []

            def open(self, request, timeout=None):
                if request.method == "GET":
                    return FakeResponse(b"")
                form = parse_qs(request.data.decode("utf-8"))
                market_id = form["mktId"][0]
                self.posted.append(market_id)
                return FakeResponse(
                    json.dumps({"OutBlock_1": blocks[market_id]}).encode(
                        "utf-8"
                    )
                )

        fake_opener = FakeOpener()
        with TemporaryDirectory() as temporary_directory:
            with patch(
                "investment_monitor.kr_universe.build_opener",
                return_value=fake_opener,
            ):
                payload = refresh_kr_universe(
                    path=Path(temporary_directory) / "kr_universe.json",
                    source="data_krx",
                    bas_dt="20260804",
                )

        kinds = {
            item["stock_code"]: item["instrument_kind"]
            for item in payload["items"]
        }
        self.assertEqual(payload["source"], "data_krx")
        self.assertEqual(kinds["005930"], "equity")
        self.assertEqual(kinds["069500"], "etf")
        self.assertEqual(kinds["500001"], "other")
        self.assertEqual(
            payload["items"][0]["market_hint"],
            "KOSPI",
        )
        self.assertEqual(fake_opener.posted, ["STK", "KSQ", "ETF", "ETN"])

    def test_krx_openapi_adapter_is_disabled(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            with self.assertRaisesRegex(KrUniverseError, "disabled"):
                refresh_kr_universe(
                    path=Path(temporary_directory) / "kr_universe.json",
                    source="krx_openapi",
                )

    def test_name_map_returns_lookup_for_web_fallback(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            cache_path = Path(temporary_directory) / "kr_universe.json"
            with patch.dict(
                os.environ,
                {
                    "DART_CORP_CODE_CACHE_PATH": str(
                        Path(temporary_directory) / "dart_corp.json"
                    )
                },
                clear=False,
            ):
                refresh_kr_universe(
                    path=cache_path,
                    source="dart_corpcode",
                    dart_client=FakeDartClient(
                        make_zip([("00593000", "삼성전자", "005930")])
                    ),
                )

            name_map = kr_universe_name_map(cache_path)

            self.assertEqual(
                name_map["005930"],
                {"name": "삼성전자", "exchange": "KRX"},
            )

    def test_add_companies_batch_uses_universe_fallback(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            database_path = Path(temporary_directory) / "web.sqlite3"
            SQLiteInformationRepository(database_path)
            repository = WebRepository(database_path)

            result = repository.add_companies_batch(
                "005930",
                ("holdings",),
                None,
                market="kr",
                name_fallback={
                    "005930": {"name": "삼성전자", "exchange": "KRX"}
                },
            )
            companies = repository.companies()

        self.assertEqual(len(result["added"]), 1)
        added = result["added"][0]
        self.assertEqual(added["name"], "삼성전자")
        self.assertEqual(added["exchange"], "KRX")
        self.assertEqual(added["mapping_status"], "unmapped")
        self.assertEqual(companies[0]["name"], "삼성전자")


if __name__ == "__main__":
    unittest.main()
