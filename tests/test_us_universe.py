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
    def __init__(self, raw, headers=None):
        self._raw = raw
        self.headers = headers or {}

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
        if request.full_url.endswith("/partitions/group/otcMarket/name/otcSecurityMaster"):
            return _FakeResponse(json.dumps({
                "datasetGroup": "otcmarket",
                "datasetName": "otcsecuritymaster",
                "partitionFields": ["asOfDate"],
                "availablePartitions": [{"partitions": ["2026-08-24"]}],
            }).encode("utf-8"))
        if request.full_url.endswith("/data/group/otcMarket/name/otcSecurityMaster"):
            rows = [
                {
                    "issueSymbolIdentifier": "AABB",
                    "securityDescription": "Asia Broadband Inc Common Stock",
                    "issueType": "Common Stock",
                    "asOfDate": "2026-08-24",
                },
                {
                    "issueSymbolIdentifier": "AACAY",
                    "securityDescription": "AAC Technologies Unsponsored ADR",
                    "issueType": "American Depositary Receipts - Unsponsored",
                    "asOfDate": "2026-08-24",
                },
            ]
            body = json.loads(request.data.decode("utf-8"))
            offset = int(body["offset"])
            limit = int(body["limit"])
            page = rows[offset:offset + limit]
            return _FakeResponse(
                json.dumps(page).encode("utf-8"),
                {
                    "record-total": str(len(rows)),
                    "record-limit": str(limit),
                    "record-offset": str(offset),
                    "record-max-limit": "5000",
                },
            )
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
            [123456, "Asia Broadband Inc", "AABB", "OTC"],
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
                minimum_otc_securities=1,
            )
        items = {item["ticker"]: item for item in result["items"]}
        self.assertEqual(set(items), {"AAPL", "QQQ", "IBM", "SPY", "AABB", "AACAY"})
        self.assertEqual(result["counts"], {
            "companies": 6, "total": 6, "stocks": 3, "etfs": 2,
            "exchange_listed": 4, "otc_active": 2,
            "sec_cik_enriched": 4, "sec_otc_cik_enriched": 1,
            "sec_market_conflicts_skipped": 0,
            "sec_otc_not_active_finra": 0,
        })
        self.assertEqual(items["QQQ"]["instrument_type"], "etf")
        self.assertEqual(items["QQQ"]["exchange"], "Nasdaq")
        self.assertEqual(items["SPY"]["instrument_type"], "etf")
        self.assertEqual(items["SPY"]["exchange"], "NYSE Arca")
        self.assertEqual(items["SPY"]["cik"], "999")
        self.assertEqual(items["AAPL"]["cik"], "320193")
        self.assertEqual(items["AABB"]["exchange"], "FINRA OTC")
        self.assertEqual(items["AABB"]["instrument_type"], "stock")
        self.assertEqual(items["AACAY"]["instrument_type"], "depositary_receipt")
        self.assertIn("OTCQX/OTCQB/Pink", " ".join(result["coverage_boundary"]["not_covered"]))
        self.assertEqual(result["source_effective_date"], "2026-08-24")
        self.assertEqual(len(opener.requests), 5)

    def test_name_map_and_search_preserve_type_and_provenance(self):
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "us.json"
            refresh_us_universe(
                path=path,
                opener=_RouteOpener(_routes()),
                minimum_otc_securities=1,
            )
            name_map = us_universe_name_map(path)
            self.assertEqual(name_map["SPY"]["instrument_type"], "etf")
            self.assertEqual(
                name_map["SPY"]["universe_source"],
                "nasdaq_trader_otherlisted",
            )
            self.assertEqual(search_us_universe("NYSE Arca", path)[0]["ticker"], "SPY")
            self.assertEqual(name_map["AABB"]["otc"], True)

    def test_sec_enrichment_failure_does_not_discard_authoritative_rows(self):
        with TemporaryDirectory() as tmp:
            result = refresh_us_universe(
                path=Path(tmp) / "us.json",
                opener=_RouteOpener(_routes(ConnectionError("SEC unavailable"))),
                minimum_otc_securities=1,
            )
        self.assertEqual(result["counts"]["total"], 6)
        self.assertEqual(result["counts"]["sec_cik_enriched"], 0)
        self.assertNotIn("sec_company_tickers_exchange", result["source"])

    def test_sec_cross_market_symbol_conflict_is_not_attached_to_otc(self):
        sec = json.dumps({
            "fields": ["cik", "name", "ticker", "exchange"],
            "data": [[123456, "Different AABB issuer", "AABB", "Nasdaq"]],
        }).encode("utf-8")
        with TemporaryDirectory() as tmp:
            result = refresh_us_universe(
                path=Path(tmp) / "us.json",
                opener=_RouteOpener(_routes(sec)),
                minimum_otc_securities=1,
            )
        aabb = next(item for item in result["items"] if item["ticker"] == "AABB")
        self.assertEqual(aabb["cik"], "")
        self.assertEqual(result["counts"]["sec_market_conflicts_skipped"], 1)

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
                    , minimum_otc_securities=1
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
                    , minimum_otc_securities=1
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
                    , minimum_otc_securities=1
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
                    , minimum_otc_securities=1
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
                    , minimum_otc_securities=1
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
                    , minimum_otc_securities=1
                )

    def test_directory_transport_failure_raises(self):
        routes = _routes()
        routes[DEFAULT_NASDAQ_LISTED_URL] = ConnectionError("boom")
        with TemporaryDirectory() as tmp:
            with self.assertRaises(UsUniverseError):
                refresh_us_universe(
                    path=Path(tmp) / "us.json", opener=_RouteOpener(routes)
                    , minimum_otc_securities=1
                )

    def test_missing_cache_is_none(self):
        with TemporaryDirectory() as tmp:
            self.assertIsNone(load_us_universe(Path(tmp) / "nope.json"))

    def test_invalid_cache_is_rejected(self):
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "us.json"
            path.write_text(
                json.dumps({
                    "items": [{"ticker": "AABB", "name": "AABB"}],
                    "counts": {"total": 2},
                }),
                encoding="utf-8",
            )
            self.assertIsNone(load_us_universe(path))


if __name__ == "__main__":
    unittest.main()
