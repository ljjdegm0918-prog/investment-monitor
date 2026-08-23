from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from investment_monitor.universe.hu_universe import (
    HuUniverseError,
    hu_universe_name_map,
    load_hu_universe,
    parse_hu_issuer_directory,
    parse_hu_issuer_profile,
    parse_hu_security_profile,
    refresh_hu_universe,
    search_hu_universe,
)


FIXTURES = Path(__file__).parent / "fixtures" / "hu_universe"


class FixtureFetcher:
    def __init__(self, *, failures=(), replacements=None):
        self.failures = set(failures)
        self.replacements = dict(replacements or {})
        self.calls = []

    def __call__(self, url):
        self.calls.append(url)
        marker = url.rsplit("/", 1)[-1]
        if marker in self.failures:
            raise OSError(f"blocked {marker}")
        if marker == "issuers":
            filename = "issuer_directory.html"
        elif marker in {"2937", "3125", "3763"}:
            filename = f"profile_{marker}.html"
        else:
            filename = f"security_{marker}.html"
        text = self.replacements.get(marker, (FIXTURES / filename).read_text(encoding="utf-8"))
        return text, {"Content-Type": "text/html"}


class HuUniverseTests(unittest.TestCase):
    def test_directory_filters_hu_real_equity_groups(self):
        candidates = parse_hu_issuer_directory(
            (FIXTURES / "issuer_directory.html").read_text(encoding="utf-8"),
            minimum_issuers=4,
            minimum_candidates=2,
        )
        self.assertEqual([row["issuer_id"] for row in candidates], [2937, 3125, 3763])
        self.assertEqual(candidates[0]["country"], "HU")

    def test_profile_and_security_parsers_preserve_stock_bond_difference(self):
        listed = parse_hu_issuer_profile(
            (FIXTURES / "profile_2937.html").read_text(encoding="utf-8")
        )
        stock = parse_hu_security_profile(
            (FIXTURES / "security_4IG.html").read_text(encoding="utf-8")
        )
        bond = parse_hu_security_profile(
            (FIXTURES / "security_4IG2031I.html").read_text(encoding="utf-8")
        )
        xtend = parse_hu_security_profile(
            (FIXTURES / "security_ASTRASUN.html").read_text(encoding="utf-8")
        )
        self.assertEqual([row["ticker"] for row in listed], ["4IG2031I", "4IG"])
        self.assertEqual(stock["equity_class"], "Ordinary share")
        self.assertEqual(stock["market"], "Prime")
        self.assertEqual(bond["equity_class"], "")
        self.assertEqual(bond["market"], "")
        self.assertEqual(xtend["equity_class"], "Ordinary share")
        self.assertEqual(xtend["market"], "")

    def test_refresh_writes_official_equities_only_and_name_map(self):
        with TemporaryDirectory() as temporary:
            path = Path(temporary) / "hu.json"
            payload = refresh_hu_universe(
                path=path,
                fetcher=FixtureFetcher(),
                requests_per_second=1000000,
                refreshed_at="2026-08-23T00:00:00+00:00",
                minimum_issuers=4,
                minimum_candidates=2,
            )
            self.assertEqual(load_hu_universe(path), payload)
            name_map = hu_universe_name_map(path)
            found = search_hu_universe("graphisoft", path)
        self.assertEqual(payload["status"], "success")
        self.assertEqual(payload["counts"]["equities"], 3)
        self.assertEqual(payload["counts"]["by_board"], {"Prime": 2, "Xtend": 1})
        self.assertEqual(
            [row["ticker"] for row in payload["items"]],
            ["4IG", "ASTRASUN", "GSPARK"],
        )
        astra = next(row for row in payload["items"] if row["ticker"] == "ASTRASUN")
        self.assertEqual(astra["board"], "Xtend")
        self.assertEqual(astra["isin"], "HU0000198320")
        self.assertNotIn("4IG2031I", name_map)
        self.assertEqual(name_map["HU0000167788"]["name"], "4iG Plc.")
        self.assertEqual(found[0]["ticker"], "GSPARK")

    def test_one_profile_failure_is_partial_but_keeps_other_issuer(self):
        with TemporaryDirectory() as temporary:
            payload = refresh_hu_universe(
                path=Path(temporary) / "hu.json",
                fetcher=FixtureFetcher(failures={"3125"}),
                requests_per_second=1000000,
                minimum_issuers=4,
                minimum_candidates=2,
            )
        self.assertEqual(payload["status"], "partial")
        self.assertEqual(
            [row["ticker"] for row in payload["items"]], ["4IG", "ASTRASUN"]
        )
        self.assertEqual(payload["counts"]["failed_issuers"], 1)
        self.assertEqual(payload["failures"][0]["issuer_id"], 3125)
        self.assertEqual(payload["cache_write_status"], "replaced_atomically")

    def test_wrong_but_valid_issuer_profile_is_not_attached_to_candidate(self):
        wrong_profile = (FIXTURES / "profile_3125.html").read_text(encoding="utf-8")
        with TemporaryDirectory() as temporary:
            payload = refresh_hu_universe(
                path=Path(temporary) / "hu.json",
                fetcher=FixtureFetcher(replacements={"2937": wrong_profile}),
                requests_per_second=1000000,
                minimum_issuers=4,
                minimum_candidates=2,
            )

        self.assertEqual(payload["status"], "partial")
        self.assertEqual(
            [row["ticker"] for row in payload["items"]], ["ASTRASUN", "GSPARK"]
        )
        self.assertEqual(payload["failures"][0]["issuer_id"], 2937)
        self.assertIn("does not match directory candidate", payload["failures"][0]["error"])

    def test_partial_refresh_does_not_replace_existing_good_cache(self):
        with TemporaryDirectory() as temporary:
            path = Path(temporary) / "hu.json"
            path.write_text(
                '{"status":"success","items":[{"ticker":"OLD","isin":"HU0000000001"}]}',
                encoding="utf-8",
            )
            payload = refresh_hu_universe(
                path=path,
                fetcher=FixtureFetcher(failures={"3125"}),
                requests_per_second=1000000,
                minimum_issuers=4,
                minimum_candidates=2,
            )

            self.assertEqual(payload["status"], "partial")
            self.assertEqual(
                payload["cache_write_status"],
                "preserved_existing_cache_after_partial_refresh",
            )
            self.assertEqual(load_hu_universe(path)["items"][0]["ticker"], "OLD")

    def test_all_profile_failures_preserve_old_cache(self):
        with TemporaryDirectory() as temporary:
            path = Path(temporary) / "hu.json"
            path.write_text('{"items":[{"ticker":"OLD"}]}', encoding="utf-8")
            with self.assertRaisesRegex(HuUniverseError, "all candidate"):
                refresh_hu_universe(
                    path=path,
                    fetcher=FixtureFetcher(failures={"2937", "3125", "3763"}),
                    requests_per_second=1000000,
                    minimum_issuers=4,
                    minimum_candidates=2,
                )
            self.assertEqual(load_hu_universe(path), {"items": [{"ticker": "OLD"}]})

    def test_directory_and_identity_contract_fail_closed(self):
        directory = (FIXTURES / "issuer_directory.html").read_text(encoding="utf-8")
        with self.assertRaisesRegex(HuUniverseError, "suspiciously small"):
            parse_hu_issuer_directory(directory, minimum_issuers=6, minimum_candidates=2)

        bad_profile = (FIXTURES / "profile_2937.html").read_text(encoding="utf-8").replace(
            "HU0000167788", "HU0000000000", 1
        )
        with TemporaryDirectory() as temporary:
            path = Path(temporary) / "hu.json"
            path.write_text('{"items":[{"ticker":"OLD"}]}', encoding="utf-8")
            with self.assertRaisesRegex(HuUniverseError, "identity conflicts"):
                refresh_hu_universe(
                    path=path,
                    fetcher=FixtureFetcher(
                        replacements={"2937": bad_profile},
                        failures={"3125", "3763"},
                    ),
                    requests_per_second=1000000,
                    minimum_issuers=4,
                    minimum_candidates=2,
                )
            self.assertEqual(load_hu_universe(path), {"items": [{"ticker": "OLD"}]})

    def test_xtend_market_fallback_rejects_ambiguous_equity_groups(self):
        directory = (FIXTURES / "issuer_directory.html").read_text(encoding="utf-8")
        directory = directory.replace(
            '{"id":"W_SME","nameEn":"Equities Xtend"}',
            '{"id":"W_SME","nameEn":"Equities Xtend"},'
            '{"id":"W_RESZVENYB","nameEn":"Equities Standard"}',
            1,
        )
        with TemporaryDirectory() as temporary:
            payload = refresh_hu_universe(
                path=Path(temporary) / "hu.json",
                fetcher=FixtureFetcher(replacements={"issuers": directory}),
                requests_per_second=1000000,
                minimum_issuers=5,
                minimum_candidates=3,
            )

        self.assertEqual(payload["status"], "partial")
        self.assertNotIn("ASTRASUN", {row["ticker"] for row in payload["items"]})
        astra_failure = next(
            failure for failure in payload["failures"] if failure["issuer_id"] == 3763
        )
        self.assertIn("no validated equity security", astra_failure["error"])

    def test_duplicate_ticker_or_isin_across_issuers_fails_closed(self):
        duplicate = (FIXTURES / "profile_3125.html").read_text(encoding="utf-8")
        duplicate = duplicate.replace("GSPARK", "4IG").replace(
            "HU0000083696", "HU0000167788"
        )
        with TemporaryDirectory() as temporary:
            path = Path(temporary) / "hu.json"
            path.write_text('{"items":[{"ticker":"OLD"}]}', encoding="utf-8")
            with self.assertRaisesRegex(HuUniverseError, "identity conflict"):
                refresh_hu_universe(
                    path=path,
                    fetcher=FixtureFetcher(replacements={"3125": duplicate}),
                    requests_per_second=1000000,
                    minimum_issuers=4,
                    minimum_candidates=2,
                )
            self.assertEqual(load_hu_universe(path), {"items": [{"ticker": "OLD"}]})


if __name__ == "__main__":
    unittest.main()
