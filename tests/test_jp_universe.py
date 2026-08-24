"""Official JPX monthly listed-issues universe tests (offline)."""

import copy
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch
from urllib.error import HTTPError

from investment_monitor.universe.jp_universe import (
    JpUniverseError,
    jp_universe_name_map,
    load_jp_universe,
    parse_jp_universe_xls,
    refresh_jp_universe,
    search_jp_universe,
)


FIXTURE = (
    Path(__file__).parent
    / "fixtures"
    / "jp_universe"
    / "listed_issues.json"
)


def _content() -> bytes:
    return b"offline-jpx-xls-fixture"


def _fixture():
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


class _Sheet:
    def __init__(self, payload) -> None:
        self._rows = [payload["headers"], *payload["rows"]]
        self.nrows = len(self._rows)
        self.ncols = len(payload["headers"])

    def cell_value(self, row, column):
        return self._rows[row][column]


class _Workbook:
    def __init__(self, payload=None) -> None:
        self._payload = payload or _fixture()
        self._sheet = _Sheet(self._payload)

    def sheet_names(self):
        return [self._payload["sheet_name"]]

    def sheet_by_index(self, _index):
        return self._sheet


class _Response:
    def __init__(self, body: bytes, headers=None) -> None:
        self._body = body
        self.headers = headers or {}

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return None

    def read(self) -> bytes:
        return self._body


class JpUniverseTests(unittest.TestCase):
    def test_parser_classifies_all_official_product_groups(self) -> None:
        with patch(
            "investment_monitor.universe.jp_universe.xlrd.open_workbook",
            return_value=_Workbook(),
        ):
            parsed = parse_jp_universe_xls(_content())
        self.assertEqual(parsed["source_effective_date"], "2026-07-31")
        self.assertEqual(parsed["counts_by_type"], {
            "equity": 5,
            "etf_etn": 1,
            "listed_fund": 1,
            "equity_contribution_security": 1,
        })
        by_ticker = {item["ticker"]: item for item in parsed["items"]}
        self.assertEqual(by_ticker["1301"]["board"], "Prime Market (Domestic)")
        self.assertEqual(by_ticker["130A"]["instrument_type"], "equity")
        self.assertEqual(by_ticker["25935"]["instrument_type"], "equity")
        self.assertEqual(by_ticker["1305"]["instrument_type"], "etf_etn")
        self.assertEqual(by_ticker["8951"]["instrument_type"], "listed_fund")
        self.assertEqual(
            by_ticker["8301"]["instrument_type"],
            "equity_contribution_security",
        )

    def test_refresh_cache_search_and_name_map(self) -> None:
        with TemporaryDirectory() as directory:
            cache = Path(directory) / "jp.json"
            with patch(
                "investment_monitor.universe.jp_universe.xlrd.open_workbook",
                return_value=_Workbook(),
            ):
                payload = refresh_jp_universe(
                    path=cache,
                    opener=lambda *_args, **_kwargs: _Response(
                        _content(),
                        {"ETag": '"jpx-20260731"', "Last-Modified": "Tue, 04 Aug 2026"},
                    ),
                    refreshed_at="2026-08-24T00:00:00+00:00",
                    minimum_items=1,
                    sleeper=lambda _: None,
                )
            loaded = load_jp_universe(cache)
            name_map = jp_universe_name_map(cache)
            matches = search_jp_universe("REIT", cache)

        self.assertEqual(payload["counts"]["total"], 8)
        self.assertTrue(payload["items"][0]["source_url"].endswith("data_e.xls"))
        self.assertEqual(loaded["source_effective_date"], "2026-07-31")
        self.assertEqual(name_map["1301"]["name"], "KYOKUYO CO.,LTD.")
        self.assertEqual(name_map["1305"]["instrument_type"], "etf_etn")
        self.assertEqual(matches[0]["ticker"], "8951")

    def test_unchanged_hash_does_not_rewrite_cache(self) -> None:
        requests = []

        def opener(request, **_kwargs):
            requests.append(dict(request.header_items()))
            return _Response(_content(), {"ETag": '"same"'})

        with TemporaryDirectory() as directory:
            cache = Path(directory) / "jp.json"
            with patch(
                "investment_monitor.universe.jp_universe.xlrd.open_workbook",
                return_value=_Workbook(),
            ):
                first = refresh_jp_universe(
                    path=cache,
                    opener=opener,
                    refreshed_at="2026-08-24T00:00:00+00:00",
                    minimum_items=1,
                    sleeper=lambda _: None,
                )
            before = cache.read_bytes()
            second = refresh_jp_universe(
                path=cache,
                opener=opener,
                refreshed_at="2026-08-25T00:00:00+00:00",
                minimum_items=1,
                sleeper=lambda _: None,
            )
            after = cache.read_bytes()

        self.assertEqual(first, second)
        self.assertEqual(before, after)
        self.assertIn(("If-none-match", '"same"'), requests[1].items())

    def test_http_304_returns_prior_cache(self) -> None:
        with TemporaryDirectory() as directory:
            cache = Path(directory) / "jp.json"
            with patch(
                "investment_monitor.universe.jp_universe.xlrd.open_workbook",
                return_value=_Workbook(),
            ):
                prior = refresh_jp_universe(
                    path=cache,
                    opener=lambda *_args, **_kwargs: _Response(
                        _content(), {"ETag": '"x"'}
                    ),
                    minimum_items=1,
                    sleeper=lambda _: None,
                )
            seen_headers = {}

            def opener(request, **_kwargs):
                seen_headers.update(dict(request.header_items()))
                raise HTTPError(request.full_url, 304, "not modified", {}, None)

            self.assertEqual(
                refresh_jp_universe(
                    path=cache,
                    opener=opener,
                    minimum_items=1,
                    sleeper=lambda _: None,
                ),
                prior,
            )
            self.assertEqual(seen_headers["If-none-match"], '"x"')

    def test_invalid_old_cache_is_never_used_for_http_304(self) -> None:
        with TemporaryDirectory() as directory:
            cache = Path(directory) / "jp.json"
            cache.write_text(
                json.dumps({"items": [{"ticker": "1301"}], "http_validators": {"etag": '"x"'}}),
                encoding="utf-8",
            )
            seen_headers = {}

            def opener(request, **_kwargs):
                seen_headers.update(dict(request.header_items()))
                raise HTTPError(request.full_url, 304, "not modified", {}, None)

            with self.assertRaisesRegex(JpUniverseError, "without a reusable"):
                refresh_jp_universe(
                    path=cache,
                    opener=opener,
                    minimum_items=1,
                    sleeper=lambda _: None,
                )
            self.assertNotIn("If-none-match", seen_headers)
            self.assertIsNone(load_jp_universe(cache))

    def test_bad_header_duplicate_and_non_xls_fail_closed(self) -> None:
        changed_header = _fixture()
        changed_header["headers"][0] = "Effective Xate"
        with patch(
            "investment_monitor.universe.jp_universe.xlrd.open_workbook",
            return_value=_Workbook(changed_header),
        ), self.assertRaisesRegex(JpUniverseError, "headers changed"):
            parse_jp_universe_xls(_content())
        duplicate = copy.deepcopy(_fixture())
        duplicate["rows"][1][1] = 1301
        with patch(
            "investment_monitor.universe.jp_universe.xlrd.open_workbook",
            return_value=_Workbook(duplicate),
        ), self.assertRaisesRegex(JpUniverseError, "repeated code"):
            parse_jp_universe_xls(_content())
        unknown = copy.deepcopy(_fixture())
        unknown["rows"][0][3] = "New Unknown Product"
        with patch(
            "investment_monitor.universe.jp_universe.xlrd.open_workbook",
            return_value=_Workbook(unknown),
        ), self.assertRaisesRegex(JpUniverseError, "unknown product"):
            parse_jp_universe_xls(_content())
        with self.assertRaisesRegex(JpUniverseError, "valid XLS"):
            parse_jp_universe_xls(b"<html>Loading</html>")

    def test_http_429_and_timeout_are_not_success(self) -> None:
        calls = []

        def limited(request, **_kwargs):
            calls.append(request.full_url)
            raise HTTPError(request.full_url, 429, "limited", {}, None)

        with TemporaryDirectory() as directory, self.assertRaisesRegex(
            JpUniverseError, "HTTP 429"
        ):
            refresh_jp_universe(
                path=Path(directory) / "jp.json",
                opener=limited,
                minimum_items=1,
                max_retries=3,
                sleeper=lambda _: None,
            )
        self.assertEqual(len(calls), 1)

        calls.clear()

        def timed_out(*_args, **_kwargs):
            calls.append("timeout")
            raise TimeoutError("slow")

        with TemporaryDirectory() as directory, self.assertRaisesRegex(
            JpUniverseError, "after retries"
        ):
            refresh_jp_universe(
                path=Path(directory) / "jp.json",
                opener=timed_out,
                minimum_items=1,
                max_retries=1,
                sleeper=lambda _: None,
            )
        self.assertEqual(calls, ["timeout", "timeout"])

    def test_date_regression_and_request_failure_preserve_cache(self) -> None:
        with TemporaryDirectory() as directory:
            cache = Path(directory) / "jp.json"
            newer = copy.deepcopy(_fixture())
            for row in newer["rows"]:
                row[0] = 20260801
            with patch(
                "investment_monitor.universe.jp_universe.xlrd.open_workbook",
                return_value=_Workbook(newer),
            ):
                prior = refresh_jp_universe(
                    path=cache,
                    opener=lambda *_args, **_kwargs: _Response(b"newer-workbook"),
                    minimum_items=1,
                    sleeper=lambda _: None,
                )
            with patch(
                "investment_monitor.universe.jp_universe.xlrd.open_workbook",
                return_value=_Workbook(),
            ), self.assertRaisesRegex(JpUniverseError, "moved backwards"):
                refresh_jp_universe(
                    path=cache,
                    opener=lambda *_args, **_kwargs: _Response(b"older-workbook"),
                    minimum_items=1,
                    sleeper=lambda _: None,
                )
            self.assertEqual(json.loads(cache.read_text()), prior)

            def forbidden(request, **_kwargs):
                raise HTTPError(request.full_url, 403, "forbidden", {}, None)

            with self.assertRaisesRegex(JpUniverseError, "HTTP 403"):
                refresh_jp_universe(path=cache, opener=forbidden)
            self.assertEqual(json.loads(cache.read_text()), prior)


if __name__ == "__main__":
    unittest.main()
