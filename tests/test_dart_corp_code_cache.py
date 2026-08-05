import io
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import time
import unittest
import zipfile

from investment_monitor import CorpCodeCache, DartRequestError


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


class FakeClient:
    def __init__(self, zip_bytes) -> None:
        self.zip_bytes = zip_bytes
        self.requested: list = []

    def get_bytes(self, path: str, parameters):
        self.requested.append((path, parameters))
        return self.zip_bytes


class CorpCodeCacheTests(unittest.TestCase):
    def test_resolves_and_normalizes_stock_codes(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            cache_path = Path(temporary_directory) / "corp.json"
            client = FakeClient(
                make_zip(
                    [
                        ("00593000", "삼성전자", "005930"),
                        ("00027000", "기아", "000270"),
                        ("00000001", "미상장법인", ""),
                    ]
                )
            )
            cache = CorpCodeCache(client=client, cache_path=cache_path)

            self.assertEqual(
                cache.resolve("005930"),
                ("00593000", "삼성전자", "005930"),
            )
            self.assertEqual(
                cache.resolve("5930"),
                ("00593000", "삼성전자", "005930"),
            )
            self.assertEqual(
                cache.resolve("000270"),
                ("00027000", "기아", "000270"),
            )
            self.assertIsNone(cache.resolve("000001"))
            self.assertEqual(client.requested, [("corpCode.xml", {})])

    def test_fresh_cache_is_used_without_download(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            cache_path = Path(temporary_directory) / "corp.json"
            cache_path.write_text(
                json.dumps({"005930": ["00593000", "삼성전자"]}),
                encoding="utf-8",
            )
            client = FakeClient(make_zip([("00000000", "다운로드금지", "000000")]))
            cache = CorpCodeCache(
                client=client,
                cache_path=cache_path,
                ttl_seconds=3600,
            )

            self.assertEqual(
                cache.resolve("005930"),
                ("00593000", "삼성전자", "005930"),
            )
            self.assertEqual(client.requested, [])

    def test_stale_cache_is_used_when_refresh_fails(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            cache_path = Path(temporary_directory) / "corp.json"
            cache_path.write_text(
                json.dumps({"005930": ["00593000", "삼성전자"]}),
                encoding="utf-8",
            )

            class FailingClient:
                def get_bytes(self, path: str, parameters):
                    raise DartRequestError("refresh failed")

            cache = CorpCodeCache(
                client=FailingClient(),
                cache_path=cache_path,
                ttl_seconds=1,
                clock=lambda: cache_path.stat().st_mtime + 60,
            )

            self.assertEqual(
                cache.resolve("005930"),
                ("00593000", "삼성전자", "005930"),
            )

    def test_download_failure_without_cache_raises(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            class FailingClient:
                def get_bytes(self, path: str, parameters):
                    raise DartRequestError("download failed")

            cache = CorpCodeCache(
                client=FailingClient(),
                cache_path=Path(temporary_directory) / "corp.json",
            )

            with self.assertRaises(DartRequestError):
                cache.resolve("005930")

    def test_all_entries_returns_full_mapping(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            cache_path = Path(temporary_directory) / "corp.json"
            client = FakeClient(
                make_zip(
                    [
                        ("00593000", "삼성전자", "005930"),
                        ("00027000", "기아", "000270"),
                        ("00000001", "미상장법인", ""),
                    ]
                )
            )
            cache = CorpCodeCache(client=client, cache_path=cache_path)

            entries = cache.all_entries()

            self.assertEqual(
                entries["005930"],
                ("00593000", "삼성전자"),
            )
            self.assertEqual(
                entries["000270"],
                ("00027000", "기아"),
            )
            self.assertNotIn("00000001", entries)


if __name__ == "__main__":
    unittest.main()
