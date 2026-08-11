"""Tests for the FSMA STORI disclosures feed (market=be).

Covers the key-free official FSMA STORI JSON surface: record parsing, the
Europe/Brussels date window (server params + authoritative client filter),
pagination, the non-be zero-HTTP skip, honest skips for BE tickers without a
universe identity, ISIN/name matching (ticker mnemonic never matches), the
registry wiring and the failure path for a single-ticker request.
"""

from datetime import date
import json
from pathlib import Path
import unittest

from investment_monitor import (
    CollectionRequest,
    StoriClient,
    StoriCompanyMatcher,
    StoriConnector,
    StoriDataError,
    StoriRequestError,
)
from investment_monitor.registry import create_default_registry


FIXTURES = Path(__file__).parent / "fixtures" / "fsma_stori"

AB_INBEV_ISIN = "BE0974293251"
WINDOW_START = date(2026, 8, 1)
WINDOW_END = date(2026, 8, 6)


class FakeResponse:
    def __init__(self, body: bytes) -> None:
        self._body = body

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return None

    def read(self) -> bytes:
        return self._body


class FakeOpener:
    def __init__(self, body: bytes) -> None:
        self.body = body
        self.requests: list = []

    def __call__(self, request, timeout=None):
        data = request.data
        if isinstance(data, bytes):
            data = data.decode("utf-8")
        self.requests.append((request.full_url, data))
        return FakeResponse(self.body)


class ScriptedOpener:
    def __init__(self, bodies):
        self.bodies = list(bodies)
        self.requests: list = []

    def __call__(self, request, timeout=None):
        data = request.data
        if isinstance(data, bytes):
            data = data.decode("utf-8")
        self.requests.append((request.full_url, data))
        return FakeResponse(self.bodies.pop(0))


def make_client(opener):
    return StoriClient(opener=opener, requests_per_second=1000)


def make_connector(body, universe=None):
    opener = FakeOpener(body)
    connector = StoriConnector(
        client=make_client(opener),
        universe=universe,
    )
    return connector, opener


def make_request(tickers, markets):
    return CollectionRequest(
        tickers=tickers,
        start_date=WINDOW_START,
        end_date=WINDOW_END,
        markets=markets,
    )


def fixture_body() -> bytes:
    return (FIXTURES / "result.json").read_bytes()


class StoriClientTests(unittest.TestCase):
    def test_remaining_result_count_at_page_limit_raises_truncation(self) -> None:
        body = json.loads(fixture_body().decode("utf-8"))
        page = dict(
            body,
            resultCount=3,
            storiResultItems=body["storiResultItems"][:2],
        )
        opener = FakeOpener(json.dumps(page).encode("utf-8"))

        with self.assertRaises(StoriDataError):
            make_client(opener).fetch_by_isin(
                AB_INBEV_ISIN,
                WINDOW_START,
                WINDOW_END,
                page_size=2,
                max_pages=1,
            )

        self.assertEqual(len(opener.requests), 1)

    def test_exact_result_count_at_page_limit_is_not_truncation(self) -> None:
        body = json.loads(fixture_body().decode("utf-8"))
        page = dict(
            body,
            resultCount=2,
            storiResultItems=body["storiResultItems"][:2],
        )
        opener = FakeOpener(json.dumps(page).encode("utf-8"))

        records = make_client(opener).fetch_by_isin(
            AB_INBEV_ISIN,
            WINDOW_START,
            WINDOW_END,
            page_size=2,
            max_pages=1,
        )

        # One of the two authoritative rows is outside the requested window;
        # returning the in-window row proves a full terminal page was accepted.
        self.assertEqual(len(records), 1)
        self.assertEqual(len(opener.requests), 1)

    def test_fetch_by_isin_parses_and_filters_brussels_window(self) -> None:
        opener = FakeOpener(fixture_body())
        client = make_client(opener)

        records = client.fetch_by_isin(
            AB_INBEV_ISIN, WINDOW_START, WINDOW_END
        )

        self.assertEqual(len(records), 5)
        ids = {record["external_id"] for record in records}
        self.assertIn("4a9a28f4-cacb-4d0b-8ae6-fe227203d1d0", ids)
        self.assertIn("90f6f9b5-5555-4d0b-8ae6-fe2272036666", ids)
        # The 2026-07-10 record is outside the window and must be dropped.
        self.assertNotIn("50b2f5c1-1111-4d0b-8ae6-fe2272032222", ids)
        self.assertIn("isinCode", opener.requests[0][1])
        self.assertIn("BE0974293251", opener.requests[0][1])
        self.assertIn('"publicationStart":"2026-08-01"', opener.requests[0][1])
        self.assertIn('"publicationEnd":"2026-08-06"', opener.requests[0][1])

    def test_fetch_by_company_name_passes_name_not_ticker(self) -> None:
        opener = FakeOpener(fixture_body())
        client = make_client(opener)

        records = client.fetch_by_company_name(
            "KBC GROUP NV", WINDOW_START, WINDOW_END
        )

        self.assertIn('"companyName":"KBC GROUP NV"', opener.requests[0][1])

    def test_pagination_stops_when_result_count_reached(self) -> None:
        body = json.loads(fixture_body().decode("utf-8"))
        page_one = dict(
            body,
            resultCount=4,
            storiResultItems=body["storiResultItems"][:2],
        )
        page_two = dict(
            body,
            resultCount=4,
            storiResultItems=body["storiResultItems"][2:4],
        )
        opener = ScriptedOpener([
            json.dumps(page_one).encode("utf-8"),
            json.dumps(page_two).encode("utf-8"),
        ])
        client = make_client(opener)

        records = client.fetch_by_isin(
            AB_INBEV_ISIN, WINDOW_START, WINDOW_END, page_size=2
        )

        self.assertEqual(len(opener.requests), 2)
        self.assertIn('"startRowIndex":0', opener.requests[0][1])
        self.assertIn('"startRowIndex":2', opener.requests[1][1])
        ids = {record["external_id"] for record in records}
        self.assertIn("4a9a28f4-cacb-4d0b-8ae6-fe227203d1d0", ids)
        self.assertIn("60c3d6e2-2222-4d0b-8ae6-fe2272033333", ids)

    def test_malformed_json_raises_data_error(self) -> None:
        client = make_client(FakeOpener(b"<html>blocked</html>"))

        with self.assertRaises(StoriDataError):
            client.fetch_by_isin(
                AB_INBEV_ISIN, WINDOW_START, WINDOW_END
            )

    def test_invalid_isin_shape_raises_value_error(self) -> None:
        client = make_client(FakeOpener(b"{}"))

        with self.assertRaises(ValueError):
            client.fetch_by_isin("FR0000121014", WINDOW_START, WINDOW_END)


class StoriConnectorTests(unittest.TestCase):
    def test_non_be_markets_are_skipped_with_zero_http(self) -> None:
        connector, opener = make_connector(fixture_body())

        items = connector.collect(
            make_request(("AAPL", "VOD"), {"AAPL": "us", "VOD": "uk"})
        )

        self.assertEqual(items, [])
        self.assertEqual(connector.last_errors, ())
        self.assertEqual(opener.requests, [])

    def test_be_without_universe_identity_is_skipped_honestly(self) -> None:
        connector, opener = make_connector(fixture_body(), universe={})

        items = connector.collect(make_request(("ABI",), {"ABI": "be"}))

        self.assertEqual(items, [])
        self.assertEqual(opener.requests, [])
        self.assertEqual(
            connector.last_errors, (("ABI", "no_universe_identity"),)
        )

    def test_be_typed_isin_collects_records(self) -> None:
        connector, opener = make_connector(fixture_body())

        items = connector.collect(
            make_request((AB_INBEV_ISIN,), {AB_INBEV_ISIN: "be"})
        )

        self.assertEqual(len(items), 3)
        first = items[0]
        self.assertEqual(first.source, "fsma_stori")
        self.assertEqual(first.source_type, "regulatory_filing")
        self.assertEqual(first.market, "be")
        self.assertEqual(first.tickers, (AB_INBEV_ISIN,))
        self.assertEqual(
            first.external_id, "4a9a28f4-cacb-4d0b-8ae6-fe227203d1d0"
        )
        self.assertEqual(first.document_type, "Half-yearly financial report")
        self.assertTrue(first.url.startswith(
            "https://webapi.fsma.be/api/v1/en/stori/download?fileDataId="
        ))
        self.assertEqual(first.raw_metadata["provider"], "fsma_stori")
        self.assertEqual(first.raw_metadata["isin"], AB_INBEV_ISIN)

    def test_be_universe_isin_matches_mnemonic_ticker(self) -> None:
        connector, _ = make_connector(
            fixture_body(),
            universe={
                "ABI": {
                    "name": "ANHEUSER-BUSCH INBEV SA/NV",
                    "exchange": "Euronext Brussels",
                    "isin": AB_INBEV_ISIN,
                }
            },
        )

        items = connector.collect(make_request(("ABI",), {"ABI": "be"}))

        self.assertEqual(len(items), 3)
        self.assertTrue(all(item.tickers == ("ABI",) for item in items))
        # Records from other issuers (KBC GROUP, ZETES) never match.
        companies = {item.issuer for item in items}
        self.assertEqual(companies, {"AB INBEV"})

    def test_be_universe_name_matches_without_isin(self) -> None:
        connector, _ = make_connector(
            fixture_body(),
            universe={"KBC": {"name": "KBC GROUP NV", "isin": ""}},
        )

        items = connector.collect(make_request(("KBC",), {"KBC": "be"}))

        self.assertEqual(len(items), 1)
        self.assertEqual(items[0].issuer, "KBC GROUP")
        self.assertEqual(items[0].external_id, "60c3d6e2-2222-4d0b-8ae6-fe2272033333")

    def test_ticker_only_never_matches(self) -> None:
        # The record mentions the mnemonic "ABI" in a document title but is
        # a different issuer (ZETES); neither name nor ISIN aligns.
        connector, _ = make_connector(
            fixture_body(),
            universe={"SOLB": {"name": "SOLVAY SA", "isin": ""}},
        )

        items = connector.collect(make_request(("SOLB",), {"SOLB": "be"}))

        self.assertEqual(items, [])
        self.assertEqual(connector.last_errors, ())

    def test_out_of_window_records_are_dropped(self) -> None:
        connector, _ = make_connector(
            fixture_body(),
            universe={"ABI": {"name": "AB INBEV", "isin": AB_INBEV_ISIN}},
        )

        items = connector.collect(make_request(("ABI",), {"ABI": "be"}))

        ids = {item.external_id for item in items}
        self.assertNotIn("50b2f5c1-1111-4d0b-8ae6-fe2272032222", ids)

    def test_record_without_document_links_to_stori_portal(self) -> None:
        connector, _ = make_connector(
            fixture_body(),
            universe={"ABI": {"name": "AB INBEV", "isin": AB_INBEV_ISIN}},
        )

        items = connector.collect(make_request(("ABI",), {"ABI": "be"}))

        portal = next(
            item for item in items
            if item.external_id == "90f6f9b5-5555-4d0b-8ae6-fe2272036666"
        )
        self.assertEqual(portal.url, "https://www.fsma.be/en/stori")

    def test_single_ticker_failure_raises_and_records_error(self) -> None:
        def failing_opener(request, timeout=None):
            raise StoriRequestError("stori blocked")

        connector = StoriConnector(
            client=make_client(failing_opener),
            universe={"ABI": {"name": "AB INBEV", "isin": AB_INBEV_ISIN}},
        )

        with self.assertRaises(StoriRequestError):
            connector.collect(make_request(("ABI",), {"ABI": "be"}))

        self.assertEqual(len(connector.last_errors), 1)
        self.assertEqual(connector.last_errors[0][0], "ABI")

    def test_registry_registers_fsma_stori_without_secret_field(self) -> None:
        registry = create_default_registry()

        self.assertIsNotNone(registry.factory_for("fsma_stori"))
        self.assertEqual(registry.secret_fields_for("fsma_stori"), ())


class StoriMatcherTests(unittest.TestCase):
    def test_company_names_match_ignores_belgian_legal_forms(self) -> None:
        self.assertTrue(
            StoriCompanyMatcher().matches(
                {
                    "company": "KBC GROUP",
                    "isin_codes": (),
                    "raw": {},
                },
                name="KBC GROUP NV",
                isin="",
            )
        )
        # Abbreviations that are not substrings of the legal name (AB INBEV
        # vs ANHEUSER-BUSCH INBEV) match by ISIN only, never by name.
        self.assertFalse(
            StoriCompanyMatcher().matches(
                {
                    "company": "AB INBEV",
                    "isin_codes": (),
                    "raw": {},
                },
                name="ANHEUSER-BUSCH INBEV SA/NV",
                isin="",
            )
        )

    def test_short_mnemonic_never_matches_full_name(self) -> None:
        self.assertFalse(
            StoriCompanyMatcher().matches(
                {"company": "AB INBEV", "isin_codes": (), "raw": {}},
                name="ABI",
                isin="",
            )
        )

    def test_isin_membership_matches_when_name_differs(self) -> None:
        self.assertTrue(
            StoriCompanyMatcher().matches(
                {
                    "company": "SOME HOLDING",
                    "isin_codes": (AB_INBEV_ISIN,),
                    "raw": {},
                },
                name="",
                isin=AB_INBEV_ISIN,
            )
        )
        self.assertFalse(
            StoriCompanyMatcher().matches(
                {
                    "company": "SOME HOLDING",
                    "isin_codes": ("BE0001234567",),
                    "raw": {},
                },
                name="",
                isin=AB_INBEV_ISIN,
            )
        )


if __name__ == "__main__":
    unittest.main()
