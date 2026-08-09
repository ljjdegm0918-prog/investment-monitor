from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from urllib.parse import parse_qs, urlsplit

from investment_monitor import (
    EsUniverseError,
    SQLiteInformationRepository,
    WebRepository,
    es_universe_name_map,
    load_es_universe,
    refresh_es_universe,
    search_es_universe,
)


FIXTURES = Path(__file__).parent / "fixtures" / "es_universe"


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
    def __init__(
        self,
        *,
        directory_error_markers=(),
        detail_error_isins=(),
    ) -> None:
        self.directory_error_markers = set(directory_error_markers)
        self.detail_error_isins = set(detail_error_isins)
        self.calls: list = []

    def __call__(self, request, timeout=None):
        url = request.full_url
        parsed = urlsplit(url)
        query = parse_qs(parsed.query)
        self.calls.append(url)
        if parsed.path.endswith("/v1/EQ/ListedCompanies"):
            if any(marker in url for marker in self.directory_error_markers):
                raise OSError(f"blocked {url}")
            if query.get("tradingSystem", [""])[0] == "MTF":
                body = (FIXTURES / "bme_mtf.json").read_bytes()
            else:
                body = (FIXTURES / "bme_main.json").read_bytes()
            return FakeResponse(body)
        if parsed.path.endswith("/v1/EQ/ShareDetailsInfo"):
            isin = query.get("isin", [""])[0]
            if isin in self.detail_error_isins:
                raise OSError(f"blocked detail {isin}")
            fixture = FIXTURES / f"detail_{isin}.json"
            if not fixture.exists():
                raise AssertionError(f"unexpected detail isin: {isin}")
            return FakeResponse(fixture.read_bytes())
        raise AssertionError(f"unexpected url: {url}")


def universe_opener(**kwargs):
    return FakeOpener(**kwargs)


class EsUniverseRefreshTests(unittest.TestCase):
    def test_refresh_writes_cache_with_counts_and_name_map(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            cache_path = Path(temporary_directory) / "es_universe.json"

            payload = refresh_es_universe(
                path=cache_path,
                opener=universe_opener(),
                refreshed_at="2026-08-10T00:00:00+00:00",
                requests_per_second=1000,
            )
            loaded = load_es_universe(cache_path)
            name_map = es_universe_name_map(cache_path)
            by_ticker = search_es_universe("SAN", cache_path)
            by_isin = search_es_universe("ES0178430E18", cache_path)
            growth = search_es_universe("BME Growth", cache_path)

        self.assertEqual(payload["source"], ["bme_equity_api"])
        self.assertEqual(
            payload["counts"],
            {
                "BME (SIBE)": 3,
                "BME (Floor)": 1,
                "BME (Latibex)": 1,
                "BME Growth": 1,
                "BME ScaleUp": 1,
            },
        )
        self.assertEqual(loaded, payload)
        self.assertEqual(
            name_map["SAN"],
            {
                "name": "BANCO SANTANDER",
                "exchange": "BME (SIBE)",
                "board": "BME (SIBE)",
                "isin": "ES0113900J37",
            },
        )
        self.assertEqual(name_map["SCAFS"]["exchange"], "BME ScaleUp")
        self.assertEqual(by_ticker[0]["ticker"], "SAN")
        self.assertEqual(by_isin[0]["ticker"], "TEF")
        self.assertTrue(
            any(item["ticker"] == "IKM" for item in growth)
        )
        self.assertNotIn("ES0109642035", loaded["counts"])

    def test_partial_board_failure_keeps_other_boards(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            cache_path = Path(temporary_directory) / "es_universe.json"

            payload = refresh_es_universe(
                path=cache_path,
                opener=universe_opener(
                    directory_error_markers=(
                        "tradingSystem=MTF",
                    )
                ),
                requests_per_second=1000,
            )

        self.assertIn("BME (SIBE)", payload["counts"])
        self.assertNotIn("BME Growth", payload["counts"])

    def test_all_sources_fail_raises(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            cache_path = Path(temporary_directory) / "es_universe.json"

            with self.assertRaises(EsUniverseError):
                refresh_es_universe(
                    path=cache_path,
                    opener=universe_opener(
                        directory_error_markers=(
                            "/v1/EQ/ListedCompanies",
                        )
                    ),
                    requests_per_second=1000,
                )

    def test_ticker_enrichment_failure_keeps_entry_without_ticker(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            cache_path = Path(temporary_directory) / "es_universe.json"

            payload = refresh_es_universe(
                path=cache_path,
                opener=universe_opener(
                    detail_error_isins=("ES0148396007",)
                ),
                requests_per_second=1000,
            )
            name_map = es_universe_name_map(cache_path)

        itx = next(
            item for item in payload["items"]
            if item["isin"] == "ES0148396007"
        )
        self.assertEqual(itx["ticker"], "")
        self.assertNotIn("ITX", name_map)
        self.assertIn("SAN", name_map)

    def test_load_and_name_map_degrade_without_cache(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            cache_path = Path(temporary_directory) / "missing.json"

            self.assertIsNone(load_es_universe(cache_path))
            self.assertEqual(es_universe_name_map(cache_path), {})
            self.assertEqual(search_es_universe("SAN", cache_path), [])

    def test_add_companies_batch_uses_es_universe_name_fallback(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            database_path = Path(temporary_directory) / "web.sqlite3"
            cache_path = Path(temporary_directory) / "es_universe.json"
            SQLiteInformationRepository(database_path)
            repository = WebRepository(database_path)
            refresh_es_universe(
                path=cache_path,
                opener=universe_opener(),
                requests_per_second=1000,
            )

            result = repository.add_companies_batch(
                "SAN.MC, TEF",
                ("holdings",),
                None,
                market="es",
                name_fallback=es_universe_name_map(cache_path),
            )

        self.assertEqual(len(result["added"]), 2)
        san = next(
            item for item in result["added"] if item["ticker"] == "SAN"
        )
        tef = next(
            item for item in result["added"] if item["ticker"] == "TEF"
        )
        self.assertEqual(san["name"], "BANCO SANTANDER")
        self.assertEqual(san["exchange"], "BME (SIBE)")
        self.assertEqual(san["mapping_status"], "unmapped")
        self.assertEqual(tef["name"], "TELEFONICA")
        self.assertEqual(tef["exchange"], "BME (SIBE)")

    def test_refresh_never_writes_information_items(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            database_path = Path(temporary_directory) / "web.sqlite3"
            cache_path = Path(temporary_directory) / "es_universe.json"
            repository = SQLiteInformationRepository(database_path)

            refresh_es_universe(
                path=cache_path,
                opener=universe_opener(),
                requests_per_second=1000,
            )

            self.assertEqual(repository.count(), 0)


if __name__ == "__main__":
    unittest.main()
