import io
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from investment_monitor import (
    SeUniverseError,
    load_se_universe,
    refresh_se_universe,
    search_se_universe,
    se_universe_name_map,
)
from investment_monitor.sources.nasdaq_se import NasdaqSeClient


FIXTURES = Path(__file__).parent / "fixtures" / "se_universe"


class _Response(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


def fixture_client(*, main=None, first_north=None):
    payloads = [
        main or json.loads((FIXTURES / "main_market.json").read_text()),
        first_north or json.loads((FIXTURES / "first_north.json").read_text()),
    ]

    def opener(request, timeout):
        return _Response(json.dumps(payloads.pop(0)).encode("utf-8"))

    return NasdaqSeClient(opener=opener, requests_per_second=1_000_000)


class SeUniverseRefreshTests(unittest.TestCase):
    def test_refresh_combines_official_boards_and_writes_auditable_cache(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            cache_path = Path(temporary_directory) / "se_universe.json"
            payload = refresh_se_universe(
                path=cache_path,
                client=fixture_client(),
                refreshed_at="2026-08-23T00:00:00+00:00",
                minimum_main_market_items=2,
                minimum_first_north_items=2,
            )
            loaded = load_se_universe(cache_path)
            name_map = se_universe_name_map(cache_path)
            by_symbol = search_se_universe("ERIC B", cache_path)
            by_isin = search_se_universe("SE0021020716", cache_path)

        self.assertEqual(loaded, payload)
        self.assertEqual(payload["counts"], {
            "total": 4,
            "main_market": 2,
            "first_north": 2,
            "excluded_non_share_rows": 0,
            "excluded_other_markets": 0,
        })
        self.assertEqual(payload["coverage"], "official_partial_nasdaq_stockholm_main_market_and_first_north")
        self.assertEqual(payload["coverage_boundary"]["official_request"]["market"], "STO")
        self.assertEqual(
            payload["coverage_boundary"]["response_constraints"]["assetClass"],
            "SHARES",
        )
        self.assertIn("NGM", payload["coverage_boundary"]["not_covered"])
        self.assertEqual(name_map["ERIC-B"]["isin"], "SE0000108656")
        eric = next(item for item in payload["items"] if item["ticker"] == "ERIC-B")
        self.assertIn("ERIC-B.ST", eric["aliases"])
        self.assertEqual(by_symbol[0]["ticker"], "ERIC-B")
        self.assertEqual(by_isin[0]["ticker"], "AAC")

    def test_partial_category_or_small_scale_does_not_replace_old_cache(self) -> None:
        first_north = json.loads((FIXTURES / "first_north.json").read_text())
        first_north["data"]["instrumentListing"]["rows"] = first_north[
            "data"
        ]["instrumentListing"]["rows"][:1]
        first_north["data"]["pagination"]["total"] = 1
        with TemporaryDirectory() as temporary_directory:
            cache_path = Path(temporary_directory) / "se_universe.json"
            cache_path.write_text('{"old":true}', encoding="utf-8")
            with self.assertRaisesRegex(SeUniverseError, "First North is suspiciously small"):
                refresh_se_universe(
                    path=cache_path,
                    client=fixture_client(first_north=first_north),
                    minimum_main_market_items=2,
                    minimum_first_north_items=2,
                )
            self.assertEqual(cache_path.read_text(encoding="utf-8"), '{"old":true}')

    def test_identity_conflict_fails_closed(self) -> None:
        first_north = json.loads((FIXTURES / "first_north.json").read_text())
        first_north["data"]["instrumentListing"]["rows"][0]["symbol"] = "ERIC B"
        with TemporaryDirectory() as temporary_directory:
            with self.assertRaisesRegex(SeUniverseError, "repeated ticker ERIC-B"):
                refresh_se_universe(
                    path=Path(temporary_directory) / "se_universe.json",
                    client=fixture_client(first_north=first_north),
                    minimum_main_market_items=2,
                    minimum_first_north_items=2,
                )

    def test_stockholm_eur_share_is_preserved(self) -> None:
        main = json.loads((FIXTURES / "main_market.json").read_text())
        main["data"]["instrumentListing"]["rows"][0]["currency"] = "EUR"
        with TemporaryDirectory() as temporary_directory:
            payload = refresh_se_universe(
                path=Path(temporary_directory) / "se_universe.json",
                client=fixture_client(main=main),
                minimum_main_market_items=2,
                minimum_first_north_items=2,
            )

        ericsson = next(row for row in payload["items"] if row["ticker"] == "ERIC-B")
        self.assertEqual(ericsson["currency"], "EUR")
        self.assertEqual(payload["counts"]["excluded_other_markets"], 0)

    def test_non_share_and_missing_identity_are_not_treated_as_empty(self) -> None:
        main = json.loads((FIXTURES / "main_market.json").read_text())
        main["data"]["instrumentListing"]["rows"][0]["assetClass"] = "ETF"
        with TemporaryDirectory() as temporary_directory:
            with self.assertRaisesRegex(SeUniverseError, "assetClass=SHARES"):
                refresh_se_universe(
                    path=Path(temporary_directory) / "se_universe.json",
                    client=fixture_client(main=main),
                    minimum_main_market_items=2,
                    minimum_first_north_items=2,
                )

    def test_load_and_search_degrade_without_cache(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            cache_path = Path(temporary_directory) / "missing.json"
            self.assertIsNone(load_se_universe(cache_path))
            self.assertEqual(se_universe_name_map(cache_path), {})
            self.assertEqual(search_se_universe("ERIC-B", cache_path), [])


if __name__ == "__main__":
    unittest.main()
