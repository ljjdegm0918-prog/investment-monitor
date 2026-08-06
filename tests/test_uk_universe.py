import io
import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch
import zipfile

from investment_monitor import (
    SQLiteInformationRepository,
    UkUniverseError,
    WebRepository,
    load_uk_universe,
    refresh_uk_universe,
    search_uk_universe,
    uk_universe_name_map,
)


def make_xml() -> bytes:
    ref = (
        "<FinInstrmGnlAttrbts><Id>{isin}</Id>"
        "<FullNm>{name}</FullNm><ShrtNm>{short}</ShrtNm>"
        "<ClssfctnTp>{cfi}</ClssfctnTp><NtnlCcy>GBP</NtnlCcy>"
        "</FinInstrmGnlAttrbts><Issr>213800TEST0000000000</Issr>"
        "<TechAttrbts><RlvntCmptntAuthrty>GB</RlvntCmptntAuthrty>"
        "<RlvntTradgVn>{venue}</RlvntTradgVn></TechAttrbts>"
    )
    records = [
        ("GB00BH4HKS39", "VODAFONE GROUP PUBLIC LIMITED COMPANY", "VODAFONE", "ESVUFR", "XLON"),
        ("GB0007980591", "BP P.L.C.", "BP", "ESVUFR", "XLON"),
        ("GB00B10RZP78", "UNILEVER PLC", "UNILEVER", "ESVUFR", "XLON"),
        ("DE000UR02JA4", "BONUS ZERTIFIKAT", "UNICREDIT", "EYCYMS", "XETR"),
    ]
    body = "".join(
        f"<RefData>{ref.format(isin=i, name=n, short=s, cfi=c, venue=v)}</RefData>"
        for i, n, s, c, v in records
    )
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<BizData xmlns="urn:iso:std:iso:20022:tech:xsd:head.003.001.01">'
        '<Pyld><Document xmlns="urn:iso:std:iso:20022:tech:xsd:auth.017.001.02">'
        "<FinInstrmRptgRefDataRpt><RptHdr/></FinInstrmRptgRefDataRpt>"
        + body
        + "</Document></Pyld></BizData>"
    ).encode("utf-8")


def make_zip() -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr(
            "FULINS_TEST_20260801_01of01.xml",
            make_xml(),
        )
    return buffer.getvalue()


def make_xml_many(count: int) -> bytes:
    ref = (
        "<FinInstrmGnlAttrbts><Id>{isin}</Id>"
        "<FullNm>{name}</FullNm><ShrtNm>{short}</ShrtNm>"
        "<ClssfctnTp>{cfi}</ClssfctnTp><NtnlCcy>GBP</NtnlCcy>"
        "</FinInstrmGnlAttrbts><Issr>213800TEST0000000000</Issr>"
        "<TechAttrbts><RlvntCmptntAuthrty>GB</RlvntCmptntAuthrty>"
        "<RlvntTradgVn>{venue}</RlvntTradgVn></TechAttrbts>"
    )
    records = [
        (
            f"GB00TEST{i:06d}",
            f"COMPANY {i}",
            f"COMPANY {i}",
            "ESVUFR",
            "XLON",
        )
        for i in range(count)
    ]
    body = "".join(
        f"<RefData>{ref.format(isin=i, name=n, short=s, cfi=c, venue=v)}</RefData>"
        for i, n, s, c, v in records
    )
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<BizData xmlns="urn:iso:std:iso:20022:tech:xsd:head.003.001.01">'
        '<Pyld><Document xmlns="urn:iso:std:iso:20022:tech:xsd:auth.017.001.02">'
        "<FinInstrmRptgRefDataRpt><RptHdr/></FinInstrmRptgRefDataRpt>"
        + body
        + "</Document></Pyld></BizData>"
    ).encode("utf-8")


def make_zip_many(count: int) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr(
            "FULINS_TEST_20260801_01of01.xml",
            make_xml_many(count),
        )
    return buffer.getvalue()


def fake_fulins_json(url: str):
    return {
        "hits": {
            "hits": [
                {
                    "_source": {
                        "file_type": "FULINS",
                        "publication_date": "2026-08-01",
                        "file_name": "FULINS_TEST_20260801_01of01.zip",
                        "download_link": (
                            "https://data.fca.org.uk/artefacts/FIRDS/"
                            "FULINS_TEST_20260801_01of01.zip"
                        ),
                    }
                }
            ]
        }
    }


class FakeResponse:
    def __init__(self, payload) -> None:
        self._body = (
            payload.encode("utf-8")
            if isinstance(payload, str)
            else payload
        )

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return None

    def read(self) -> bytes:
        return self._body


class FakeOpenFigiOpener:
    def __init__(self, tickers_by_isin, row_overrides=None) -> None:
        self.tickers_by_isin = tickers_by_isin
        self.row_overrides = row_overrides or {}
        self.calls: list = []

    def __call__(self, request, timeout=None):
        self.calls.append(request.full_url)
        body = json.loads(request.data.decode("utf-8"))
        rows = []
        for entry in body:
            isin = entry["idValue"]
            if isin in self.row_overrides:
                rows.append(self.row_overrides[isin])
                continue
            ticker = self.tickers_by_isin.get(isin)
            if ticker:
                rows.append(
                    {"data": [{"ticker": ticker, "exchCode": "LN"}]}
                )
            else:
                rows.append({"warning": "not found"})
        return FakeResponse(json.dumps(rows))


class UkUniverseParseTests(unittest.TestCase):
    def test_parses_xlon_equities_and_skips_non_uk(self) -> None:
        from investment_monitor.uk_universe import _parse_zip_bytes

        records, mic_seen = _parse_zip_bytes(make_zip())
        by_isin = {record["isin"]: record for record in records}

        self.assertIn("GB00BH4HKS39", by_isin)
        self.assertEqual(by_isin["GB00BH4HKS39"]["ticker"], "VOD")
        self.assertEqual(
            by_isin["GB00BH4HKS39"]["name"],
            "VODAFONE GROUP PUBLIC LIMITED COMPANY",
        )
        self.assertEqual(by_isin["GB00BH4HKS39"]["instrument_kind"], "equity")
        self.assertIn("GB00B10RZP78", by_isin)
        self.assertEqual(by_isin["GB00B10RZP78"]["ticker"], "ULVR")
        self.assertNotIn("DE000UR02JA4", by_isin)
        self.assertIn("XLON", mic_seen)
        self.assertIn("XETR", mic_seen)


class UkUniverseRefreshTests(unittest.TestCase):
    def test_refresh_writes_cache_and_name_map(self) -> None:
        import investment_monitor.uk_universe as uk

        def fake_get_json(url: str):
            return {
                "hits": {
                    "hits": [
                        {
                            "_source": {
                                "file_type": "FULINS",
                                "publication_date": "2026-08-01",
                                "file_name": "FULINS_E_20260801_01of01.zip",
                                "download_link": (
                                    "https://data.fca.org.uk/artefacts/FIRDS/"
                                    "FULINS_E_20260801_01of01.zip"
                                ),
                            }
                        },
                        {
                            "_source": {
                                "file_type": "FULINS",
                                "publication_date": "2026-08-01",
                                "file_name": "FULINS_H_20260801_01of06.zip",
                                "download_link": (
                                    "https://data.fca.org.uk/artefacts/FIRDS/"
                                    "FULINS_H_20260801_01of06.zip"
                                ),
                            }
                        },
                    ]
                }
            }

        with TemporaryDirectory() as temporary_directory:
            cache_path = Path(temporary_directory) / "uk_universe.json"
            with patch.object(
                uk,
                "_get_json",
                side_effect=fake_get_json,
            ), patch.object(
                uk,
                "_download_bytes",
                return_value=make_zip(),
            ), patch(
                "investment_monitor.uk_universe.time.sleep"
            ):
                payload = refresh_uk_universe(
                    path=cache_path,
                    enrich_tickers=False,
                )
                loaded = load_uk_universe(cache_path)
                name_map = uk_universe_name_map(cache_path)

        self.assertEqual(payload["source"], "firds")
        self.assertEqual(payload["publication_date"], "2026-08-01")
        self.assertGreaterEqual(len(payload["items"]), 3)
        self.assertEqual(loaded, payload)
        self.assertEqual(
            name_map["VOD"],
            {
                "name": "VODAFONE GROUP PUBLIC LIMITED COMPANY",
                "exchange": "LSE",
            },
        )

    def test_unknown_source_raises(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            with self.assertRaisesRegex(UkUniverseError, "Unknown"):
                refresh_uk_universe(
                    path=Path(temporary_directory) / "uk_universe.json",
                    source="other",
                )

    def test_load_and_name_map_degrade_without_cache(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            cache_path = Path(temporary_directory) / "missing.json"

            self.assertIsNone(load_uk_universe(cache_path))
            self.assertEqual(uk_universe_name_map(cache_path), {})

    def test_add_companies_batch_uses_universe_name_fallback(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            database_path = Path(temporary_directory) / "web.sqlite3"
            SQLiteInformationRepository(database_path)
            repository = WebRepository(database_path)

            result = repository.add_companies_batch(
                "VOD",
                ("holdings",),
                None,
                market="uk",
                name_fallback={
                    "VOD": {
                        "name": "VODAFONE GROUP PUBLIC LIMITED COMPANY",
                        "exchange": "LSE",
                    }
                },
            )

        self.assertEqual(len(result["added"]), 1)
        added = result["added"][0]
        self.assertEqual(added["name"], "VODAFONE GROUP PUBLIC LIMITED COMPANY")
        self.assertEqual(added["exchange"], "LSE")
        self.assertEqual(added["mapping_status"], "unmapped")

    def refresh_many(self, cache_path, count=300, opener=None, **kwargs):
        import investment_monitor.uk_universe as uk

        with patch.object(
            uk,
            "_get_json",
            side_effect=fake_fulins_json,
        ), patch.object(
            uk,
            "_download_bytes",
            return_value=make_zip_many(count),
        ), patch("investment_monitor.uk_universe.time.sleep"):
            return refresh_uk_universe(
                path=cache_path,
                openfigi_opener=opener,
                **kwargs,
            )

    def test_openfigi_enrichment_adds_hundreds_of_tickers(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            cache_path = Path(temporary_directory) / "uk_universe.json"
            tickers_by_isin = {
                f"GB00TEST{i:06d}": f"T{i:04d}"
                for i in range(300)
            }
            opener = FakeOpenFigiOpener(tickers_by_isin)

            payload = self.refresh_many(
                cache_path,
                count=300,
                opener=opener,
            )
            name_map = uk_universe_name_map(cache_path)
            results = search_uk_universe("T0042", cache_path)

        ticked = [
            item
            for item in payload["items"]
            if item.get("ticker")
        ]
        self.assertGreaterEqual(len(ticked), 300)
        self.assertGreater(len(ticked), 9)
        self.assertEqual(
            ticked[42]["ticker_source"],
            "openfigi",
        )
        self.assertIn("T0042", name_map)
        self.assertEqual(results[0]["ticker"], "T0042")

    def test_openfigi_failure_keeps_previous_tickers(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            cache_path = Path(temporary_directory) / "uk_universe.json"
            tickers_by_isin = {
                f"GB00TEST{i:06d}": f"T{i:04d}"
                for i in range(300)
            }
            self.refresh_many(
                cache_path,
                count=300,
                opener=FakeOpenFigiOpener(tickers_by_isin),
            )

            def failing_opener(request, timeout=None):
                raise OSError("OpenFIGI blocked")

            payload = self.refresh_many(
                cache_path,
                count=300,
                opener=failing_opener,
            )

        by_isin = {
            item["isin"]: item
            for item in payload["items"]
        }
        self.assertEqual(by_isin["GB00TEST000042"]["ticker"], "T0042")

    def test_openfigi_prefers_ln_exchange(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            cache_path = Path(temporary_directory) / "uk_universe.json"
            tickers_by_isin = {
                f"GB00TEST{i:06d}": f"T{i:04d}"
                for i in range(300)
            }
            opener = FakeOpenFigiOpener(
                tickers_by_isin,
                row_overrides={
                    "GB00TEST000042": {
                        "data": [
                            {"ticker": "T9999", "exchCode": "ET"},
                            {"ticker": "T0042", "exchCode": "LN"},
                        ]
                    }
                },
            )

            payload = self.refresh_many(
                cache_path,
                count=300,
                opener=opener,
            )

        by_isin = {
            item["isin"]: item
            for item in payload["items"]
        }
        self.assertEqual(by_isin["GB00TEST000042"]["ticker"], "T0042")

    def test_openfigi_warning_rows_do_not_break_other_isins(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            cache_path = Path(temporary_directory) / "uk_universe.json"
            tickers_by_isin = {
                f"GB00TEST{i:06d}": f"T{i:04d}"
                for i in range(300)
            }
            opener = FakeOpenFigiOpener(
                tickers_by_isin,
                row_overrides={
                    "GB00TEST000000": {"warning": "not found"},
                    "GB00TEST000001": {"error": "invalid isin"},
                },
            )

            payload = self.refresh_many(
                cache_path,
                count=300,
                opener=opener,
            )

        by_isin = {
            item["isin"]: item
            for item in payload["items"]
        }
        self.assertEqual(by_isin["GB00TEST000000"]["ticker"], "")
        self.assertEqual(by_isin["GB00TEST000001"]["ticker"], "")
        self.assertEqual(by_isin["GB00TEST000042"]["ticker"], "T0042")

    def test_openfigi_url_reads_environment_override(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            cache_path = Path(temporary_directory) / "uk_universe.json"
            opener = FakeOpenFigiOpener(
                {f"GB00TEST{i:06d}": f"T{i:04d}" for i in range(300)}
            )
            with patch.dict(
                os.environ,
                {"UK_UNIVERSE_OPENFIGI_URL": "https://example.test/openfigi"},
                clear=False,
            ):
                self.refresh_many(
                    cache_path,
                    count=300,
                    opener=opener,
                )

        self.assertTrue(opener.calls)
        self.assertTrue(
            opener.calls[0].startswith("https://example.test/openfigi")
        )

    def test_search_matches_name_and_degrades_without_cache(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            cache_path = Path(temporary_directory) / "uk_universe.json"
            missing = Path(temporary_directory) / "missing.json"

            self.refresh_many(
                cache_path,
                count=300,
                opener=FakeOpenFigiOpener(
                    {f"GB00TEST{i:06d}": f"T{i:04d}" for i in range(300)}
                ),
            )
            by_name = search_uk_universe("COMPANY 42", cache_path)
            empty = search_uk_universe("zzz-nope", cache_path)
            no_cache = search_uk_universe("VOD", missing)

        self.assertEqual(by_name[0]["ticker"], "T0042")
        self.assertEqual(empty, [])
        self.assertEqual(no_cache, [])


if __name__ == "__main__":
    unittest.main()
