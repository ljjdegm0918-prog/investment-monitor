"""US official Nasdaq Trader stock/ETF universe tests (offline)."""

import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from investment_monitor.us_universe import (
    DEFAULT_NASDAQ_LISTED_URL,
    DEFAULT_OTHER_LISTED_URL,
    DEFAULT_SEC_URL,
    UsUniverseError,
    load_us_universe,
    refresh_us_universe,
    search_us_universe,
    us_universe_name_map,
)


NASDAQ_ROWS = b"""Symbol|Security Name|Market Category|Test Issue|Financial Status|Round Lot Size|ETF|NextShares
AAPL|Apple Inc. - Common Stock|Q|N|N|100|N|N
QQQ|Invesco QQQ Trust ETF|G|N|N|100|Y|N
ZTEST|Nasdaq Test Issue|Q|Y|N|100|N|N
File Creation Time: 0816202617:03|||||||
"""

OTHER_ROWS = b"""ACT Symbol|Security Name|Exchange|CQS Symbol|ETF|Round Lot Size|Test Issue|NASDAQ Symbol
IBM|International Business Machines Common Stock|N|IBM|N|100|N|IBM
SPY|SPDR S&P 500 ETF Trust|P|SPY|Y|100|N|SPY
ATEST|Other Test Issue|A|ATEST|N|100|Y|ATEST
File Creation Time: 0816202617:03|||||||
"""


class _FakeResponse:
    def __init__(self, raw):
        self._raw = raw
        self.headers = {}

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def read(self):
        return self._raw


class _RouteOpener:
    def __init__(self, routes):
        self.routes = routes
        self.requests = []

    def __call__(self, request, timeout=None):
        self.requests.append(request)
        value = self.routes[request.full_url]
        if isinstance(value, Exception):
            raise value
        return _FakeResponse(value)


def _sec_payload():
    return json.dumps({
        "fields": ["cik", "name", "ticker", "exchange"],
        "data": [
            [320193, "Apple Inc.", "AAPL", "Nasdaq"],
            [51143, "IBM", "IBM", "NYSE"],
            [999, "Wrong ETF type", "SPY", "NYSE Arca"],
        ],
    }).encode("utf-8")


def _routes(sec=None):
    return {
        DEFAULT_NASDAQ_LISTED_URL: NASDAQ_ROWS,
        DEFAULT_OTHER_LISTED_URL: OTHER_ROWS,
        DEFAULT_SEC_URL: _sec_payload() if sec is None else sec,
    }


class UsUniverseTests(unittest.TestCase):
    def test_refresh_combines_official_stock_and_etf_directories(self):
        opener = _RouteOpener(_routes())
        with TemporaryDirectory() as tmp:
            result = refresh_us_universe(
                path=Path(tmp) / "us.json",
                opener=opener,
                refreshed_at="2026-08-16T00:00:00+00:00",
            )
        items = {item["ticker"]: item for item in result["items"]}
        self.assertEqual(set(items), {"AAPL", "QQQ", "IBM", "SPY"})
        self.assertEqual(result["counts"], {
            "companies": 4, "total": 4, "stocks": 2, "etfs": 2,
            "sec_cik_enriched": 3,
        })
        self.assertEqual(items["QQQ"]["instrument_type"], "etf")
        self.assertEqual(items["QQQ"]["exchange"], "Nasdaq")
        self.assertEqual(items["SPY"]["instrument_type"], "etf")
        self.assertEqual(items["SPY"]["exchange"], "NYSE Arca")
        self.assertEqual(items["SPY"]["cik"], "999")
        self.assertEqual(items["AAPL"]["cik"], "320193")
        self.assertEqual(result["coverage_boundary"], "exchange_listed_only_otc_not_proven")
        self.assertEqual(len(opener.requests), 3)

    def test_name_map_and_search_preserve_type_and_provenance(self):
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "us.json"
            refresh_us_universe(path=path, opener=_RouteOpener(_routes()))
            name_map = us_universe_name_map(path)
            self.assertEqual(name_map["SPY"]["instrument_type"], "etf")
            self.assertEqual(
                name_map["SPY"]["universe_source"],
                "nasdaq_trader_otherlisted",
            )
            self.assertEqual(search_us_universe("NYSE Arca", path)[0]["ticker"], "SPY")

    def test_sec_enrichment_failure_does_not_discard_authoritative_rows(self):
        with TemporaryDirectory() as tmp:
            result = refresh_us_universe(
                path=Path(tmp) / "us.json",
                opener=_RouteOpener(_routes(ConnectionError("SEC unavailable"))),
            )
        self.assertEqual(result["counts"]["total"], 4)
        self.assertEqual(result["counts"]["sec_cik_enriched"], 0)
        self.assertNotIn("sec_company_tickers_exchange", result["source"])

    def test_missing_required_directory_field_fails_closed(self):
        routes = _routes()
        routes[DEFAULT_NASDAQ_LISTED_URL] = (
            b"Symbol|Security Name|Test Issue\nAAPL|Apple|N\n"
            b"File Creation Time: 0816202617:03||\n"
        )
        with TemporaryDirectory() as tmp:
            with self.assertRaisesRegex(UsUniverseError, "missing fields"):
                refresh_us_universe(
                    path=Path(tmp) / "us.json", opener=_RouteOpener(routes)
                )

    def test_empty_authoritative_directory_fails_closed(self):
        routes = _routes()
        routes[DEFAULT_OTHER_LISTED_URL] = (
            b"ACT Symbol|Security Name|Exchange|CQS Symbol|ETF|Round Lot Size|Test Issue|NASDAQ Symbol\n"
            b"File Creation Time: 0816202617:03|||||||\n"
        )
        with TemporaryDirectory() as tmp:
            with self.assertRaisesRegex(UsUniverseError, "no usable entries"):
                refresh_us_universe(
                    path=Path(tmp) / "us.json", opener=_RouteOpener(routes)
                )

    def test_truncated_directory_without_creation_footer_fails_closed(self):
        routes = _routes()
        routes[DEFAULT_NASDAQ_LISTED_URL] = (
            b"Symbol|Security Name|Market Category|Test Issue|Financial Status|Round Lot Size|ETF|NextShares\n"
            b"AAPL|Apple Inc. - Common Stock|Q|N|N|100|N|N\n"
        )
        with TemporaryDirectory() as tmp:
            with self.assertRaisesRegex(UsUniverseError, "truncated"):
                refresh_us_universe(
                    path=Path(tmp) / "us.json", opener=_RouteOpener(routes)
                )

    def test_invalid_etf_flag_fails_closed(self):
        routes = _routes()
        routes[DEFAULT_NASDAQ_LISTED_URL] = (
            b"Symbol|Security Name|Market Category|Test Issue|Financial Status|Round Lot Size|ETF|NextShares\n"
            b"AAPL|Apple Inc. - Common Stock|Q|N|N|100||N\n"
            b"File Creation Time: 0816202617:03|||||||\n"
        )
        with TemporaryDirectory() as tmp:
            with self.assertRaisesRegex(UsUniverseError, "invalid Y/N flag"):
                refresh_us_universe(
                    path=Path(tmp) / "us.json", opener=_RouteOpener(routes)
                )

    def test_malformed_row_width_fails_closed(self):
        routes = _routes()
        routes[DEFAULT_OTHER_LISTED_URL] = (
            b"ACT Symbol|Security Name|Exchange|CQS Symbol|ETF|Round Lot Size|Test Issue|NASDAQ Symbol\n"
            b"IBM|International Business Machines|N|IBM|N|100|N|IBM|EXTRA\n"
            b"File Creation Time: 0816202617:03|||||||\n"
        )
        with TemporaryDirectory() as tmp:
            with self.assertRaisesRegex(UsUniverseError, "malformed row"):
                refresh_us_universe(
                    path=Path(tmp) / "us.json", opener=_RouteOpener(routes)
                )

    def test_blank_symbol_row_fails_closed(self):
        routes = _routes()
        routes[DEFAULT_NASDAQ_LISTED_URL] = (
            b"Symbol|Security Name|Market Category|Test Issue|Financial Status|Round Lot Size|ETF|NextShares\n"
            b"|Missing symbol|Q|N|N|100|N|N\n"
            b"File Creation Time: 0816202617:03|||||||\n"
        )
        with TemporaryDirectory() as tmp:
            with self.assertRaisesRegex(UsUniverseError, "blank symbol row"):
                refresh_us_universe(
                    path=Path(tmp) / "us.json", opener=_RouteOpener(routes)
                )

    def test_directory_transport_failure_raises(self):
        routes = _routes()
        routes[DEFAULT_NASDAQ_LISTED_URL] = ConnectionError("boom")
        with TemporaryDirectory() as tmp:
            with self.assertRaises(UsUniverseError):
                refresh_us_universe(
                    path=Path(tmp) / "us.json", opener=_RouteOpener(routes)
                )

    def test_missing_cache_is_none(self):
        with TemporaryDirectory() as tmp:
            self.assertIsNone(load_us_universe(Path(tmp) / "nope.json"))


if __name__ == "__main__":
    unittest.main()
