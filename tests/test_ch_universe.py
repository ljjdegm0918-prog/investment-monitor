"""Official SIX share/ETF universe tests (all network responses are fixtures)."""

import copy
from io import BytesIO
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from urllib.error import HTTPError
from urllib.parse import parse_qs, urlparse

from investment_monitor import (
    ChUniverseError,
    SQLiteInformationRepository,
    WebRepository,
    ch_universe_name_map,
    load_ch_universe,
    refresh_ch_universe,
    search_ch_universe,
)
from investment_monitor.universe.ch_universe import (
    ETF_COLUMNS,
    SHARE_COLUMNS,
    SPONSORED_SHARE_COLUMNS,
    SixFqsClient,
)


FIXTURES = Path(__file__).parent / "fixtures" / "ch_universe"


class _Response:
    def __init__(self, body: bytes) -> None:
        self._body = body

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return None

    def read(self) -> bytes:
        return self._body


def _fixture(name: str):
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def _records(name: str, columns):
    payload = _fixture(name)
    return [dict(zip(columns, row)) for row in payload["rowData"]]


def _scope_timings():
    values = {
        "swiss_shares": 1787548024724,
        "foreign_shares": 1787548025724,
        "sponsored_foreign_shares": 1787548026224,
        "etfs": 1787548026724,
    }
    from datetime import datetime, timezone

    result = {}
    for scope, millis in values.items():
        instant = datetime.fromtimestamp(millis / 1000, timezone.utc).isoformat()
        result[scope] = {
            "delay_minutes": 15,
            "from": instant,
            "to": instant,
            "delayed_millis_from": millis,
            "delayed_millis_to": millis,
        }
    return result


def _fixture_opener(request, **_kwargs):
    query = parse_qs(urlparse(request.full_url).query)
    where = query["where"][0]
    name = {
        "PortalSegment=EQ*TitleSegment=SA": "swiss_shares_page1.json",
        "PortalSegment=EQ*TitleSegment=AA": "foreign_shares_page1.json",
        "PortalSegment=EQ*TitleSegment=SP": "sponsored_foreign_shares_page1.json",
        "ProductLine=ET*PortalSegment=FU": "etfs_page1.json",
    }[where]
    return _Response(json.dumps(_fixture(name)).encode())


class ChUniverseTests(unittest.TestCase):
    def test_client_fetches_all_required_official_scopes(self) -> None:
        client = SixFqsClient(
            opener=_fixture_opener,
            requests_per_second=1000,
            sleeper=lambda _seconds: None,
        )
        scopes = client.fetch_all(page_size=2)
        self.assertEqual({key: len(value) for key, value in scopes.items()}, {
            "swiss_shares": 2,
            "foreign_shares": 2,
            "sponsored_foreign_shares": 2,
            "etfs": 2,
        })
        self.assertEqual(scopes["swiss_shares"][0]["TitleSegment"], "SA")
        self.assertEqual(scopes["foreign_shares"][0]["TitleSegment"], "AA")
        self.assertEqual(
            scopes["sponsored_foreign_shares"][0]["TradingBaseCurrency"],
            "CHF",
        )
        self.assertEqual(scopes["etfs"][0]["ProductLine"], "ET")

    def test_refresh_classifies_trading_lines_and_writes_atomically(self) -> None:
        client = SixFqsClient(
            opener=_fixture_opener,
            requests_per_second=1000,
            sleeper=lambda _seconds: None,
        )
        with TemporaryDirectory() as directory:
            cache = Path(directory) / "ch.json"
            payload = refresh_ch_universe(
                path=cache,
                client=client,
                refreshed_at="2026-08-24T00:00:00+00:00",
                minimum_swiss_shares=1,
                minimum_foreign_shares=1,
                minimum_sponsored_foreign_shares=1,
                minimum_etfs=1,
                page_size=2,
            )
            loaded = load_ch_universe(cache)
            name_map = ch_universe_name_map(cache)
            etfs = search_ch_universe("LU3322521785", cache)
            sponsored = search_ch_universe("ABBV", cache)

        self.assertEqual(payload["counts"]["total"], 8)
        self.assertEqual(
            payload["counts_by_type"],
            {"equity": 4, "sponsored_foreign_share": 2, "etf": 2},
        )
        self.assertEqual(payload["source_effective_date"], "2026-08-24")
        self.assertEqual(
            payload["source_effective_at"],
            "2026-08-24T05:07:06.724000+00:00",
        )
        self.assertFalse(payload["source_effective_range"]["single_snapshot"])
        self.assertEqual(payload["excluded_counts"]["unknown_security_type"], 0)
        self.assertEqual(loaded["coverage"], "official_partial_six_exchange_metadata")
        self.assertEqual(name_map["ABBN"]["isin"], "CH0012221716")
        self.assertEqual(name_map["ABBV"]["isin"], "US00287Y1091")
        self.assertNotIn("EBND", name_map)
        self.assertEqual(payload["counts"]["ambiguous_tickers"], 2)
        self.assertEqual(len(etfs), 2)
        self.assertEqual({item["trading_currency"] for item in etfs}, {"CHF", "USD"})
        self.assertTrue(all(item["instrument_type"] == "etf" for item in etfs))
        self.assertEqual(len(sponsored), 2)
        self.assertEqual(
            {item["trading_currency"] for item in sponsored}, {"CHF", "USD"}
        )
        self.assertTrue(
            all(item["primary_listing_outside_switzerland"] for item in sponsored)
        )

    def test_rights_are_not_misclassified_as_equity_and_unknown_types_fail(self) -> None:
        swiss = _records("swiss_shares_page1.json", SHARE_COLUMNS)
        swiss.extend(
            [
                {
                    "ShortName": "PARTICIPATION CERTIFICATE",
                    "ValorId": "CH0000000001CHF4",
                    "ISIN": "CH0000000001",
                    "ValorSymbol": "PART",
                    "ValorNumber": 1,
                    "SecTypeCode": "PC",
                    "SecTypeDesc": "Participation Certificate",
                    "ListingSegmentCode": "SR",
                    "ListingSegmentDesc": "Swiss Reporting Standard",
                    "TitleSegment": "SA",
                    "PortalSegment": "EQ",
                },
                {
                    "ShortName": "REALSTONE ANR",
                    "ValorId": "CH0000000002CHF4",
                    "ISIN": "CH0000000002",
                    "ValorSymbol": "RSP1",
                    "ValorNumber": 2,
                    "SecTypeCode": "RI",
                    "SecTypeDesc": "Right",
                    "ListingSegmentCode": "DR",
                    "ListingSegmentDesc": "Rights",
                    "TitleSegment": "SA",
                    "PortalSegment": "EQ",
                },
            ]
        )

        class Client:
            def fetch_all(self, **_kwargs):
                self.last_scope_metadata = _scope_timings()
                return {
                    "swiss_shares": swiss,
                    "foreign_shares": _records("foreign_shares_page1.json", SHARE_COLUMNS),
                    "sponsored_foreign_shares": _records(
                        "sponsored_foreign_shares_page1.json",
                        SPONSORED_SHARE_COLUMNS,
                    ),
                    "etfs": _records("etfs_page1.json", ETF_COLUMNS),
                }

        with TemporaryDirectory() as directory:
            cache = Path(directory) / "ch.json"
            payload = refresh_ch_universe(
                path=cache,
                client=Client(),
                minimum_swiss_shares=1,
                minimum_foreign_shares=1,
                minimum_sponsored_foreign_shares=1,
                minimum_etfs=1,
            )
            name_map = ch_universe_name_map(cache)
        self.assertEqual(payload["counts_by_type"]["subscription_right"], 1)
        self.assertEqual(payload["counts_by_type"]["participation_certificate"], 1)
        self.assertNotIn("RSP1", name_map)
        self.assertEqual(name_map["PART"]["instrument_type"], "participation_certificate")

        swiss[0] = {**swiss[0], "SecTypeCode": "ZZ", "SecTypeDesc": "New Type"}
        with TemporaryDirectory() as directory, self.assertRaisesRegex(
            ChUniverseError, "unknown SecTypeCode"
        ):
            refresh_ch_universe(
                path=Path(directory) / "ch.json",
                client=Client(),
                minimum_swiss_shares=1,
                minimum_foreign_shares=1,
                minimum_sponsored_foreign_shares=1,
                minimum_etfs=1,
            )

    def test_multiple_pages_complete_and_overlap_fails_closed(self) -> None:
        swiss = _fixture("swiss_shares_page1.json")
        swiss["totalRows"] = 3
        second = copy.deepcopy(swiss)
        second["pageNumber"] = 2
        second["rowData"] = [[
            "NESTLE N", "CH0038863350CHF4", "CH0038863350", "NESN",
            3886335, "RS", "Registered Share", "SR",
            "Swiss Reporting Standard", "SA", "EQ",
        ]]

        def opener(request, **_kwargs):
            query = parse_qs(urlparse(request.full_url).query)
            if query["where"][0].endswith("=SA"):
                payload = swiss if query["page"][0] == "1" else second
            else:
                payload = json.loads(_fixture_opener(request).read())
            return _Response(json.dumps(payload).encode())

        client = SixFqsClient(opener=opener, requests_per_second=1000, sleeper=lambda _: None)
        scopes = client.fetch_all(page_size=2)
        self.assertEqual(len(scopes["swiss_shares"]), 3)

        second["rowData"] = [swiss["rowData"][0]]
        with self.assertRaisesRegex(ChUniverseError, "repeated ValorId"):
            client.fetch_all(page_size=2)

    def test_pagination_or_column_drift_fails_closed(self) -> None:
        changed = _fixture("swiss_shares_page1.json")
        changed["totalRows"] = 3
        changed["rowData"] = changed["rowData"][:1]

        def opener(_request, **_kwargs):
            return _Response(json.dumps(changed).encode())

        client = SixFqsClient(opener=opener, requests_per_second=1000, sleeper=lambda _: None)
        with self.assertRaisesRegex(ChUniverseError, "page length"):
            client.fetch_all(page_size=2)

        changed = _fixture("swiss_shares_page1.json")
        changed["colNames"][0] = "Changed"
        with self.assertRaisesRegex(ChUniverseError, "column contract"):
            SixFqsClient(
                opener=lambda *_args, **_kwargs: _Response(json.dumps(changed).encode()),
                requests_per_second=1000,
                sleeper=lambda _: None,
            ).fetch_all(page_size=2)

        changed = _fixture("swiss_shares_page1.json")
        changed["delayedMillis"] += 1000
        with self.assertRaisesRegex(ChUniverseError, "disagrees"):
            SixFqsClient(
                opener=lambda *_args, **_kwargs: _Response(json.dumps(changed).encode()),
                requests_per_second=1000,
                sleeper=lambda _: None,
            ).fetch_all(page_size=2)

    def test_http_429_and_loading_html_are_not_success(self) -> None:
        calls = []

        def limited(request, **_kwargs):
            calls.append(request.full_url)
            raise HTTPError(request.full_url, 429, "limited", {}, BytesIO())

        with self.assertRaisesRegex(ChUniverseError, "HTTP 429"):
            SixFqsClient(
                opener=limited,
                max_retries=3,
                requests_per_second=1000,
                sleeper=lambda _: None,
            ).fetch_all(page_size=2)
        self.assertEqual(len(calls), 1)

        with self.assertRaisesRegex(ChUniverseError, "non-JSON"):
            SixFqsClient(
                opener=lambda *_args, **_kwargs: _Response(b"<html>Loading</html>"),
                requests_per_second=1000,
                sleeper=lambda _: None,
            ).fetch_all(page_size=2)

    def test_failed_refresh_preserves_prior_cache(self) -> None:
        class BrokenClient:
            def fetch_all(self):
                raise ChUniverseError("broken")

        with TemporaryDirectory() as directory:
            cache = Path(directory) / "ch.json"
            cache.write_text('{"items": [{"ticker": "OLD"}]}', encoding="utf-8")
            with self.assertRaises(ChUniverseError):
                refresh_ch_universe(path=cache, client=BrokenClient())
            self.assertEqual(json.loads(cache.read_text())["items"][0]["ticker"], "OLD")

    def test_load_and_name_map_degrade_without_cache(self) -> None:
        with TemporaryDirectory() as directory:
            cache = Path(directory) / "missing.json"
            self.assertIsNone(load_ch_universe(cache))
            self.assertEqual(ch_universe_name_map(cache), {})
            self.assertEqual(search_ch_universe("NESN", cache), [])

    def test_add_companies_batch_without_universe_is_unmapped(self) -> None:
        with TemporaryDirectory() as directory:
            database = Path(directory) / "web.sqlite3"
            SQLiteInformationRepository(database)
            repository = WebRepository(database)
            result = repository.add_companies_batch(
                "NESN.SW", ("holdings",), None, market="ch", name_fallback={}
            )
        self.assertEqual(result["added"][0]["ticker"], "NESN")
        self.assertEqual(result["added"][0]["mapping_status"], "unmapped")


if __name__ == "__main__":
    unittest.main()
