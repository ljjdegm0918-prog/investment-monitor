from pathlib import Path
from tempfile import TemporaryDirectory
import json
import unittest
from unittest.mock import patch
from urllib.parse import urlsplit

from investment_monitor import (
    CaUniverseError,
    SQLiteInformationRepository,
    WebRepository,
    ca_universe_name_map,
    load_ca_universe,
    refresh_ca_universe,
    search_ca_universe,
)
from investment_monitor.ca_universe import (
    parse_ca_universe_overlay,
    parse_cse_bulletin_html,
    parse_cse_official_export,
    parse_cse_profile_html,
)


FIXTURES = Path(__file__).parent / "fixtures" / "ca_universe"


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


def tsx_opener(**kwargs):
    return FakeOpener(
        {
            "/json/company-directory/search/tsx/^": (
                FIXTURES / "tsx.json"
            ).read_bytes()
        },
        **kwargs,
    )


def tsxv_opener(**kwargs):
    return FakeOpener(
        {
            "/json/company-directory/search/tsxv/^": (
                FIXTURES / "tsxv.json"
            ).read_bytes()
        },
        **kwargs,
    )


def _cse_rows():
    rows = [
        {
            "id": index,
            "symbol": f"C{index:03d}",
            "securityName": f"CSE Example {index} Corp.",
            "status": "Active",
            "delistedDate": None,
            "slug": f"cse-example-{index}-corp",
            "mocEligible": False,
        }
        for index in range(1, 101)
    ]
    rows.extend(
        [
            {
                "id": 101,
                "symbol": "REUSE",
                "securityName": "Old Reuse Corp.",
                "status": "Delisted",
                "delistedDate": "2024-02-01",
                "slug": "old-reuse-corp",
                "mocEligible": False,
            },
            {
                "id": 102,
                "symbol": "REUSE",
                "securityName": "Current Reuse Corp.",
                "status": "Suspended",
                "delistedDate": None,
                "slug": "current-reuse-corp",
                "mocEligible": False,
            },
            {
                "id": 103,
                "symbol": "OLD",
                "securityName": "Historical Corp.",
                "status": "Delisted",
                "delistedDate": "2025-05-01",
                "slug": "historical-corp",
                "mocEligible": False,
            },
        ]
    )
    return rows


def cse_opener(**kwargs):
    return FakeOpener(
        {
            "/api/companies/all": json.dumps(_cse_rows()).encode("utf-8"),
        },
        **kwargs,
    )


class CaUniverseRefreshTests(unittest.TestCase):
    def test_refresh_writes_cache_with_counts_and_name_map(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            cache_path = Path(temporary_directory) / "ca_universe.json"

            payload = refresh_ca_universe(
                path=cache_path,
                tsx_opener=tsx_opener(),
                tsxv_opener=tsxv_opener(),
                cse_opener=cse_opener(),
                refreshed_at="2026-08-08T00:00:00+00:00",
            )
            loaded = load_ca_universe(cache_path)
            name_map = ca_universe_name_map(cache_path)
            by_ticker = search_ca_universe("SHOP", cache_path)
            by_name = search_ca_universe("1911 Gold", cache_path)

        self.assertEqual(
            payload["source"],
            ["cse_directory", "tsx_directory", "tsxv_directory"],
        )
        self.assertEqual(
            payload["counts"],
            {"TSX": 4, "TSXV": 4, "CSE": 102},
        )
        self.assertEqual(loaded, payload)
        self.assertEqual(
            name_map["RY"],
            {
                "name": "Royal Bank of Canada",
                "exchange": "TSX",
                "board": "TSX",
            },
        )
        self.assertEqual(name_map["SHOP"]["exchange"], "TSX")
        self.assertEqual(name_map["SHOP"]["board"], "TSX")
        self.assertEqual(name_map["SHOP.WT"]["exchange"], "TSX")
        self.assertEqual(
            name_map["ONE"],
            {
                "name": "01 Quantum Inc.",
                "exchange": "TSXV",
                "board": "TSXV",
            },
        )
        self.assertEqual(by_ticker[0]["ticker"], "SHOP")
        self.assertEqual(by_name[0]["ticker"], "AUMB")

    def test_duplicate_symbol_prefers_tsx_board(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            cache_path = Path(temporary_directory) / "ca_universe.json"

            payload = refresh_ca_universe(
                path=cache_path,
                tsx_opener=tsx_opener(),
                tsxv_opener=tsxv_opener(),
                cse_opener=cse_opener(),
                refreshed_at="2026-08-08T00:00:00+00:00",
            )
            name_map = ca_universe_name_map(cache_path)

        self.assertEqual(name_map["RY"]["exchange"], "TSX")
        self.assertEqual(payload["counts"]["TSXV"], 4)
        ry_listings = [
            item
            for item in payload["items"]
            if item["ticker"] == "RY"
        ]
        self.assertEqual(
            [(item["exchange"], item["symbol"]) for item in ry_listings],
            [("TSX", "RY"), ("TSXV", "RY")],
        )

    def test_cse_live_directory_keeps_history_and_resolves_recycled_symbol(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            payload = refresh_ca_universe(
                path=Path(temporary_directory) / "ca_universe.json",
                tsx_opener=tsx_opener(),
                tsxv_opener=tsxv_opener(),
                cse_opener=cse_opener(),
                refreshed_at="2026-08-22T00:00:00+00:00",
            )

        reused = next(
            item for item in payload["items"] if item["listing_id"] == "CSE:REUSE"
        )
        historical = next(
            item for item in payload["items"] if item["listing_id"] == "CSE:OLD"
        )
        self.assertEqual(reused["issuer_name"], "Current Reuse Corp.")
        self.assertEqual(reused["previous_issuer_names"], ["Old Reuse Corp."])
        self.assertTrue(reused["symbol_history_ambiguous"])
        self.assertEqual(reused["status"], "suspended")
        self.assertEqual(historical["status"], "delisted")
        self.assertEqual(historical["delisted_at"], "2025-05-01")
        self.assertEqual(reused["source"], "cse_directory")
        self.assertEqual(
            reused["source_url"],
            "https://website-data-api-v2.thecse.com/api/companies/all",
        )

    def test_partial_failure_keeps_successful_board(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            cache_path = Path(temporary_directory) / "ca_universe.json"

            payload = refresh_ca_universe(
                path=cache_path,
                tsx_opener=tsx_opener(),
                tsxv_opener=tsxv_opener(
                    error_paths=("/json/company-directory/search/tsxv/^",)
                ),
                cse_opener=cse_opener(error_paths=("/api/companies/all",)),
                refreshed_at="2026-08-08T00:00:00+00:00",
            )

        self.assertEqual(payload["counts"]["TSX"], 4)
        self.assertEqual(payload["counts"]["TSXV"], 0)
        self.assertEqual(payload["counts"]["CSE"], 0)
        self.assertEqual(payload["source"], ["tsx_directory"])

    def test_all_sources_fail_raises(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            cache_path = Path(temporary_directory) / "ca_universe.json"

            with self.assertRaises(CaUniverseError):
                refresh_ca_universe(
                    path=cache_path,
                    tsx_opener=tsx_opener(
                        error_paths=("/json/company-directory/search/tsx/^",)
                    ),
                    tsxv_opener=tsxv_opener(
                        error_paths=("/json/company-directory/search/tsxv/^",)
                    ),
                    cse_opener=cse_opener(error_paths=("/api/companies/all",)),
                )

    def test_load_and_name_map_degrade_without_cache(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            cache_path = Path(temporary_directory) / "missing.json"

            self.assertIsNone(load_ca_universe(cache_path))
            self.assertEqual(ca_universe_name_map(cache_path), {})
            self.assertEqual(search_ca_universe("SHOP", cache_path), [])

    def test_add_companies_batch_uses_ca_universe_name_fallback(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            database_path = Path(temporary_directory) / "web.sqlite3"
            cache_path = Path(temporary_directory) / "ca_universe.json"
            SQLiteInformationRepository(database_path)
            repository = WebRepository(database_path)
            refresh_ca_universe(
                path=cache_path,
                tsx_opener=tsx_opener(),
                tsxv_opener=tsxv_opener(),
                cse_opener=cse_opener(),
            )

            result = repository.add_companies_batch(
                "RY.TO, AUMB.V",
                ("holdings",),
                None,
                market="ca",
                name_fallback=ca_universe_name_map(cache_path),
            )

        self.assertEqual(len(result["added"]), 2)
        royal = next(
            item for item in result["added"] if item["ticker"] == "RY"
        )
        aumb = next(
            item for item in result["added"] if item["ticker"] == "AUMB"
        )
        self.assertEqual(royal["name"], "Royal Bank of Canada")
        self.assertEqual(royal["exchange"], "TSX")
        self.assertEqual(aumb["name"], "1911 Gold Corporation")
        self.assertEqual(aumb["exchange"], "TSXV")
        self.assertEqual(royal["mapping_status"], "unmapped")

    def test_refresh_never_writes_information_items(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            database_path = Path(temporary_directory) / "web.sqlite3"
            cache_path = Path(temporary_directory) / "ca_universe.json"
            repository = SQLiteInformationRepository(database_path)

            refresh_ca_universe(
                path=cache_path,
                tsx_opener=tsx_opener(),
                tsxv_opener=tsxv_opener(),
                cse_opener=cse_opener(),
            )

            self.assertEqual(repository.count(), 0)

    def test_listing_contract_has_provenance_and_optional_fields(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            cache_path = Path(temporary_directory) / "ca_universe.json"
            payload = refresh_ca_universe(
                path=cache_path,
                tsx_opener=tsx_opener(),
                tsxv_opener=tsxv_opener(),
                cse_opener=cse_opener(),
                refreshed_at="2026-08-08T00:00:00+00:00",
            )

        shop = next(
            item
            for item in payload["items"]
            if item["listing_id"] == "TSX:SHOP"
        )
        self.assertEqual(shop["issuer_name"], "Shopify Inc.")
        self.assertEqual(shop["symbol"], "SHOP")
        self.assertEqual(shop["country"], "CA")
        self.assertEqual(shop["source"], "tsx_directory")
        self.assertEqual(shop["last_verified_at"], "2026-08-08T00:00:00+00:00")
        self.assertIsNone(shop["website"])
        self.assertIsNone(shop["investor_relations_url"])
        self.assertIsNone(shop["sec_cik"])

    def test_injected_cse_export_is_offline_and_preserves_rename_alias(self) -> None:
        export = {
            "source_url": "https://primary.thecse.com/listing/listed-companies/",
            "exported_at": "2026-08-21T20:00:00-04:00",
            "items": [
                {
                    "symbol": "NEW",
                    "issuer_name": "New Name Corp.",
                    "website": "https://newname.example/",
                    "investor_relations_url": "https://newname.example/investors",
                    "previous_symbols": ["OLD"],
                    "previous_issuer_names": ["Old Name Corp."],
                }
            ],
        }
        with TemporaryDirectory() as temporary_directory:
            cache_path = Path(temporary_directory) / "ca_universe.json"
            payload = refresh_ca_universe(
                path=cache_path,
                tsx_opener=tsx_opener(),
                tsxv_opener=tsxv_opener(),
                cse_export=export,
            )
            name_map = ca_universe_name_map(cache_path)

        cse = next(item for item in payload["items"] if item["listing_id"] == "CSE:NEW")
        self.assertEqual(payload["counts"]["CSE"], 1)
        self.assertEqual(cse["source"], "cse_official_export")
        self.assertEqual(cse["source_url"], export["source_url"])
        self.assertEqual(cse["website"], "https://newname.example/")
        self.assertEqual(name_map["OLD"]["name"], "New Name Corp.")
        self.assertEqual(name_map["OLD"]["exchange"], "CSE")

    def test_cse_export_rejects_non_cse_provenance_and_bad_structure(self) -> None:
        with self.assertRaises(CaUniverseError):
            parse_cse_official_export(
                {
                    "source_url": "https://example.invalid/export.csv",
                    "exported_at": "2026-08-22T00:00:00+00:00",
                    "items": [{"symbol": "ABC", "issuer_name": "Example Inc."}],
                }
            )
        with self.assertRaises(CaUniverseError):
            parse_ca_universe_overlay(
                {
                    "last_verified_at": "2026-08-22T00:00:00+00:00",
                    "items": [{"exchange": "CSE", "symbol": "ABC"}],
                }
            )

    def test_refresh_loads_reviewed_cse_export_from_environment(self) -> None:
        export = {
            "source_url": "https://thecse.com/listing/listed-companies/",
            "exported_at": "2026-08-22T00:00:00+00:00",
            "items": [{"symbol": "ENV", "issuer_name": "Environment Corp."}],
        }
        with TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            export_path = root / "cse.json"
            export_path.write_text(json.dumps(export), encoding="utf-8")
            with patch.dict(
                "os.environ", {"CA_CSE_UNIVERSE_EXPORT_PATH": str(export_path)}
            ):
                payload = refresh_ca_universe(
                    path=root / "universe.json",
                    tsx_opener=tsx_opener(),
                    tsxv_opener=tsxv_opener(),
                )
        self.assertEqual(payload["counts"]["CSE"], 1)
        self.assertIn("cse_official_export", payload["source"])

    def test_overlay_enriches_listing_without_losing_exchange_source(self) -> None:
        overlay = {
            "last_verified_at": "2026-08-22T00:00:00+00:00",
            "items": [
                {
                    "exchange": "TSX",
                    "symbol": "SHOP",
                    "issuer_name": "Shopify Inc.",
                    "investor_relations_url": "https://shopifyinvestors.com/",
                    "previous_symbols": ["SHOPOLD"],
                }
            ],
        }
        with TemporaryDirectory() as temporary_directory:
            cache_path = Path(temporary_directory) / "ca_universe.json"
            payload = refresh_ca_universe(
                path=cache_path,
                tsx_opener=tsx_opener(),
                tsxv_opener=tsxv_opener(),
                cse_opener=cse_opener(),
                overlay=overlay,
            )
            name_map = ca_universe_name_map(cache_path)

        shop = next(item for item in payload["items"] if item["listing_id"] == "TSX:SHOP")
        self.assertEqual(shop["source"], "tsx_directory")
        self.assertEqual(shop["overlay_source"], "ca_config_overlay")
        self.assertEqual(shop["investor_relations_url"], "https://shopifyinvestors.com/")
        self.assertEqual(name_map["SHOPOLD"]["name"], "Shopify Inc.")

    def test_cse_offline_profile_and_bulletin_parsers(self) -> None:
        profile = parse_cse_profile_html(
            (FIXTURES / "cse_profile.html").read_text(encoding="utf-8"),
            source_url="https://v3.thecse.com/listings/example-corp/",
            last_verified_at="2026-08-22T00:00:00+00:00",
        )
        bulletin = parse_cse_bulletin_html(
            (FIXTURES / "cse_bulletin_resume.html").read_text(encoding="utf-8"),
            source_url="https://thecse.com/bulletin/2026-0109-resumption-example-corp-exm/",
            last_verified_at="2026-08-22T00:00:00+00:00",
        )

        self.assertEqual(profile["issuer_name"], "Example Corp.")
        self.assertEqual(profile["symbol"], "EXM")
        self.assertEqual(profile["source_url"], "https://v3.thecse.com/listings/example-corp/")
        self.assertEqual(profile["website"], "https://example.test/")
        self.assertEqual(profile["investor_relations_url"], "https://example.test/investors")
        self.assertEqual(bulletin["event_type"], "resume")
        self.assertEqual(bulletin["symbol"], "EXM")
        self.assertEqual(bulletin["published_at"], "2026-01-09T09:30:00-05:00")

    def test_cse_bulletin_parser_fails_closed_without_timestamp_or_event(self) -> None:
        html = "<html><h1>Example Corp. (EXM)</h1></html>"
        with self.assertRaises(CaUniverseError):
            parse_cse_bulletin_html(
                html,
                source_url="https://thecse.com/bulletin/example/",
                last_verified_at="2026-08-22T00:00:00+00:00",
            )


if __name__ == "__main__":
    unittest.main()
