"""Tests for the BE tradeable universe cache (market=be, BE-2).

Mirrors ``test_fr_universe.py`` / ``test_nl_universe.py``: the refresh reads
the same key-free Euronext live all-stocks CSV family and keeps only rows
whose market segment mentions Brussels (``Euronext Brussels`` / ``Euronext
Growth Brussels`` / ``Euronext Access Brussels`` plus multi-venue rows).
Decoy rows (pure Paris/Amsterdam/Milan/Lisbon, Global Equity Market,
Trading After Hours, EuroTLX, Expert Market) are excluded. Also verifies
the BE-1 FSMA STORI alignment: once the universe cache supplies an
ISIN/name, a mnemonic BE ticker can drive disclosure matching.
"""

from datetime import date
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from urllib.parse import urlsplit

from investment_monitor import (
    BeUniverseError,
    CollectionRequest,
    SQLiteInformationRepository,
    StoriClient,
    StoriConnector,
    WebRepository,
    be_universe_name_map,
    load_be_universe,
    refresh_be_universe,
    search_be_universe,
)


FIXTURES = Path(__file__).parent / "fixtures" / "be_universe"
FSMA_FIXTURES = Path(__file__).parent / "fixtures" / "fsma_stori"


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
        if path in self.fixtures:
            return FakeResponse(self.fixtures[path])
        raise AssertionError(f"unexpected url: {request.full_url}")


def directory_opener(**kwargs):
    return FakeOpener(
        {
            "/en/pd_es/data/stocks/download": (
                FIXTURES / "euronext_be_sample.csv"
            ).read_bytes()
        },
        **kwargs,
    )


def fsma_opener(body: bytes):
    return FakeOpener({"/api/v1/en/stori/result": body})


class BeUniverseRefreshTests(unittest.TestCase):
    def test_refresh_writes_cache_with_counts_and_name_map(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            cache_path = Path(temporary_directory) / "be_universe.json"

            payload = refresh_be_universe(
                path=cache_path,
                opener=directory_opener(),
                refreshed_at="2026-08-10T00:00:00+00:00",
            )
            loaded = load_be_universe(cache_path)
            name_map = be_universe_name_map(cache_path)
            by_ticker = search_be_universe("ABI", cache_path)
            by_isin = search_be_universe("BE0974293251", cache_path)
            by_board = search_be_universe("Growth Brussels", cache_path)

        self.assertEqual(payload["source"], ["euronext_live_csv"])
        self.assertEqual(
            payload["counts"],
            {
                "Euronext Brussels": 3,
                "Euronext Brussels, Paris": 1,
                "Euronext Growth Brussels": 2,
                "Euronext Access Brussels": 2,
                "Euronext Amsterdam, Brussels": 1,
                "Euronext Paris, Brussels": 1,
            },
        )
        self.assertEqual(loaded, payload)
        self.assertEqual(
            name_map["ABI"],
            {
                "name": "AB INBEV",
                "exchange": "Euronext Brussels",
                "board": "Euronext Brussels",
                "isin": "BE0974293251",
            },
        )
        self.assertEqual(
            name_map["SOLB"]["exchange"], "Euronext Brussels, Paris"
        )
        self.assertEqual(
            name_map["CAND"]["exchange"], "Euronext Growth Brussels"
        )
        self.assertEqual(
            name_map["MLTV"]["exchange"], "Euronext Access Brussels"
        )
        self.assertEqual(
            name_map["AD"]["exchange"], "Euronext Amsterdam, Brussels"
        )
        self.assertEqual(
            name_map["TTE"]["exchange"], "Euronext Paris, Brussels"
        )
        # Decoys never enter the cache: foreign-only boards and the
        # Global Equity Market / Trading After Hours / EuroTLX / Expert
        # Market noise rows.
        for decoy in ("1ABI", "2KBC", "4UCB", "ASML", "MC", "ENI", "GALP", "NMC"):
            self.assertNotIn(decoy, name_map)
        self.assertEqual(by_ticker[0]["ticker"], "ABI")
        self.assertEqual(by_isin[0]["ticker"], "ABI")
        self.assertEqual(
            {item["ticker"] for item in by_board}, {"CAND", "SOFT"}
        )

    def test_all_sources_fail_raises(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            cache_path = Path(temporary_directory) / "be_universe.json"

            with self.assertRaises(BeUniverseError):
                refresh_be_universe(
                    path=cache_path,
                    opener=directory_opener(
                        error_paths=("/en/pd_es/data/stocks/download",)
                    ),
                )

    def test_load_and_name_map_degrade_without_cache(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            cache_path = Path(temporary_directory) / "missing.json"

            self.assertIsNone(load_be_universe(cache_path))
            self.assertEqual(be_universe_name_map(cache_path), {})
            self.assertEqual(search_be_universe("ABI", cache_path), [])

    def test_add_companies_batch_uses_be_universe_name_fallback(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            database_path = Path(temporary_directory) / "web.sqlite3"
            cache_path = Path(temporary_directory) / "be_universe.json"
            SQLiteInformationRepository(database_path)
            repository = WebRepository(database_path)
            refresh_be_universe(
                path=cache_path,
                opener=directory_opener(),
            )

            result = repository.add_companies_batch(
                "ABI.BR, KBC",
                ("holdings",),
                None,
                market="be",
                name_fallback=be_universe_name_map(cache_path),
            )

        self.assertEqual(len(result["added"]), 2)
        abi = next(item for item in result["added"] if item["ticker"] == "ABI")
        kbc = next(item for item in result["added"] if item["ticker"] == "KBC")
        self.assertEqual(abi["name"], "AB INBEV")
        self.assertEqual(abi["exchange"], "Euronext Brussels")
        self.assertEqual(kbc["name"], "KBC")
        self.assertEqual(kbc["exchange"], "Euronext Brussels")
        self.assertEqual(abi["mapping_status"], "unmapped")

    def test_refresh_never_writes_information_items(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            database_path = Path(temporary_directory) / "web.sqlite3"
            cache_path = Path(temporary_directory) / "be_universe.json"
            repository = SQLiteInformationRepository(database_path)

            refresh_be_universe(
                path=cache_path,
                opener=directory_opener(),
            )

            self.assertEqual(repository.count(), 0)

    def test_universe_name_map_feeds_fsma_stori_matching(self) -> None:
        """BE-2 -> BE-1 alignment: mnemonic ticker gets an ISIN/name from
        the universe cache and the FSMA STORI connector can match."""
        with TemporaryDirectory() as temporary_directory:
            cache_path = Path(temporary_directory) / "be_universe.json"
            refresh_be_universe(
                path=cache_path,
                opener=directory_opener(),
            )
            opener = fsma_opener(
                (FSMA_FIXTURES / "result.json").read_bytes()
            )
            connector = StoriConnector(
                client=StoriClient(opener=opener, requests_per_second=1000),
                universe=be_universe_name_map(cache_path),
            )
            items = connector.collect(
                CollectionRequest(
                    tickers=("ABI",),
                    start_date=date(2026, 8, 1),
                    end_date=date(2026, 8, 6),
                    markets={"ABI": "be"},
                )
            )

        self.assertEqual(len(items), 3)
        self.assertTrue(all(item.tickers == ("ABI",) for item in items))
        self.assertEqual({item.issuer for item in items}, {"AB INBEV"})
        # The mnemonic ticker ABI matched only because the universe cache
        # supplied the AB INBEV ISIN (BE0974293251); no manual identity was
        # passed to the connector.
        self.assertEqual(opener.calls, ["/api/v1/en/stori/result"])
        self.assertEqual(connector.last_errors, ())


if __name__ == "__main__":
    unittest.main()
