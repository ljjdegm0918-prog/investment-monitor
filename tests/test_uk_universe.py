import io
import json
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
                payload = refresh_uk_universe(path=cache_path)
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


if __name__ == "__main__":
    unittest.main()
