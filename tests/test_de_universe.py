from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from urllib.parse import urlsplit

from investment_monitor.universe.de_universe import (
    DeUniverseError,
    de_universe_name_map,
    load_de_universe,
    refresh_de_universe,
    search_de_universe,
)

FIXTURES = Path(__file__).parent / "fixtures" / "de_universe"


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
    def __init__(self, fixtures: dict, error_paths=()) -> None:
        self.fixtures = fixtures
        self.error_paths = set(error_paths)
        self.calls: list = []

    def __call__(self, request, timeout=None):
        path = urlsplit(request.full_url).path
        self.calls.append(path)
        if path in self.error_paths:
            raise OSError(f"blocked {path}")
        for key, body in self.fixtures.items():
            if path.endswith(key) or key in path:
                return FakeResponse(body)
        raise AssertionError(f"unexpected url: {request.full_url}")


class DeUniverseTests(unittest.TestCase):
    def test_refresh_keeps_cs_and_includes_etf_etn_etc(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            cache_path = Path(temporary_directory) / "de_universe.json"
            opener = FakeOpener(
                {
                    "t7-xetr-allTradableInstruments.csv": (
                        FIXTURES / "xetra_de_sample.csv"
                    ).read_bytes()
                }
            )
            payload = refresh_de_universe(
                path=cache_path,
                opener=opener,
                refreshed_at="2026-08-10T00:00:00+00:00",
            )
            loaded = load_de_universe(cache_path)
            name_map = de_universe_name_map(cache_path)
            hits = search_de_universe("SAP", cache_path)
            etf_hits = search_de_universe("ETF1", cache_path)

        self.assertEqual(payload["source"], ["xetra_all_tradable_csv"])
        self.assertEqual(
            payload["counts"],
            {
                "DAX": 2,
                "ETF": 1,
                "EXCHANGE TRADED NOTES": 1,
                "EXCHANGE TRADED COMMODITIES": 1,
            },
        )
        self.assertEqual(
            payload["counts_by_type"],
            {"CS": 2, "ETF": 1, "ETN": 1, "ETC": 1},
        )
        self.assertEqual(loaded["counts_by_type"], payload["counts_by_type"])
        self.assertEqual(name_map["SAP"]["isin"], "DE0007164600")
        self.assertEqual(name_map["SIE"]["board"], "DAX")
        self.assertEqual(name_map["SAP"]["instrument_type"], "CS")
        self.assertIn("ETF1", name_map)
        self.assertEqual(name_map["ETF1"]["isin"], "DE000ETF0001")
        self.assertEqual(name_map["ETF1"]["board"], "ETF")
        self.assertEqual(name_map["ETF1"]["instrument_type"], "ETF")
        self.assertEqual(
            name_map["ETN1"]["instrument_type"],
            "ETN",
        )
        self.assertEqual(
            name_map["ETN1"]["board"],
            "EXCHANGE TRADED NOTES",
        )
        self.assertEqual(name_map["ETC1"]["instrument_type"], "ETC")
        self.assertNotIn("SKIP", name_map)
        self.assertEqual(hits[0]["ticker"], "SAP")
        self.assertEqual(etf_hits[0]["ticker"], "ETF1")

    def test_add_companies_batch_backfills_etf_entry(self) -> None:
        from investment_monitor import (
            SQLiteInformationRepository,
            WebRepository,
        )

        with TemporaryDirectory() as temporary_directory:
            database_path = Path(temporary_directory) / "web.sqlite3"
            cache_path = Path(temporary_directory) / "de_universe.json"
            SQLiteInformationRepository(database_path)
            repository = WebRepository(database_path)
            refresh_de_universe(
                path=cache_path,
                opener=FakeOpener(
                    {
                        "t7-xetr-allTradableInstruments.csv": (
                            FIXTURES / "xetra_de_sample.csv"
                        ).read_bytes()
                    }
                ),
            )

            result = repository.add_companies_batch(
                "ETF1.DE, SAP",
                ("holdings",),
                None,
                market="de",
                name_fallback=de_universe_name_map(cache_path),
            )

        self.assertEqual(len(result["added"]), 2)
        etf1 = next(
            item for item in result["added"] if item["ticker"] == "ETF1"
        )
        sap = next(
            item for item in result["added"] if item["ticker"] == "SAP"
        )
        self.assertEqual(etf1["name"], "SOME ETF")
        self.assertEqual(etf1["exchange"], "ETF")
        self.assertEqual(etf1["mapping_status"], "unmapped")
        self.assertEqual(sap["name"], "SAP SE O.N.")
        self.assertEqual(sap["exchange"], "DAX")

    def test_refresh_failure_raises(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            cache_path = Path(temporary_directory) / "de_universe.json"
            opener = FakeOpener(
                {"t7-xetr-allTradableInstruments.csv": b""},
                error_paths={
                    "/resource/blob/1528/a31c10e3183f4c5dd721f9c7f9eaaaea/data/"
                    "t7-xetr-allTradableInstruments.csv"
                },
            )
            with self.assertRaises(DeUniverseError):
                refresh_de_universe(path=cache_path, opener=opener)


if __name__ == "__main__":
    unittest.main()
