"""Tests for the AMF OAM disclosures feed (market=fr).

Covers both accepted payload shapes (plain ``result`` list and
Elasticsearch ``hits.hits[]._source`` wrapper), the non-fr skip path, the
client-side Europe/Paris date window, and universe-identity matching
(company name / ISIN match; ticker-only never matches).
"""

from datetime import date
import json
from pathlib import Path
import unittest

from investment_monitor import (
    AmfOamClient,
    AmfOamConnector,
    CollectionRequest,
)


FIXTURES = Path(__file__).parent / "fixtures" / "amf_oam"

LVMH_IDENTITY = {
    "name": "LVMH Mo\u00ebt Hennessy Louis Vuitton SE",
    "isin": "FR0000121014",
}


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
        self.requested: list = []

    def __call__(self, request, timeout=None):
        self.requested.append(request.full_url)
        return FakeResponse(self.body)


def make_connector(body: bytes, universe=None):
    opener = FakeOpener(body)
    connector = AmfOamConnector(
        client=AmfOamClient(opener=opener, requests_per_second=1000),
        universe=universe,
    )
    return connector, opener


def make_request(tickers, markets, start=date(2026, 8, 1), end=date(2026, 8, 6)):
    return CollectionRequest(
        tickers=tickers,
        start_date=start,
        end_date=end,
        markets=markets,
    )


class AmfOamFixtureParseTests(unittest.TestCase):
    def test_result_payload_fixture_parses_and_matches(self) -> None:
        connector, opener = make_connector(
            (FIXTURES / "result_payload.json").read_bytes(),
            universe={"MC": LVMH_IDENTITY},
        )

        items = connector.collect(make_request(("MC",), {"MC": "fr"}))

        self.assertEqual(len(items), 2)
        ids = {item.external_id for item in items}
        self.assertEqual(ids, {"26-000123", "26-000999"})
        self.assertTrue(all(item.market == "fr" for item in items))
        self.assertTrue(all(item.source == "amf_oam" for item in items))
        self.assertTrue(all(item.tickers == ("MC",) for item in items))
        self.assertIn("informations?", opener.requested[0])

    def test_hits_payload_fixture_parses_and_matches(self) -> None:
        connector, _ = make_connector(
            (FIXTURES / "hits_payload.json").read_bytes(),
            universe={"MC": LVMH_IDENTITY},
        )

        items = connector.collect(make_request(("MC",), {"MC": "fr"}))

        self.assertEqual(len(items), 1)
        self.assertEqual(items[0].external_id, "26-000321")
        self.assertEqual(items[0].document_type, "Rapport financier")


class AmfOamNonFRSkipTests(unittest.TestCase):
    def test_non_fr_market_is_skipped_without_http(self) -> None:
        connector, opener = make_connector(
            (FIXTURES / "result_payload.json").read_bytes(),
            universe={"MC": LVMH_IDENTITY},
        )

        items = connector.collect(
            make_request(("AAPL", "VOD"), {"AAPL": "us", "VOD": "uk"})
        )

        self.assertEqual(items, [])
        self.assertEqual(connector.last_errors, ())
        self.assertEqual(opener.requested, [])


class AmfOamDateWindowTests(unittest.TestCase):
    def test_client_date_window_constrains_result_payload(self) -> None:
        opener = FakeOpener((FIXTURES / "result_payload.json").read_bytes())
        client = AmfOamClient(opener=opener, requests_per_second=1000)

        payload = client.fetch_payload(
            date(2026, 8, 1), date(2026, 8, 6), limit=100
        )

        ids = {
            record["numeroConcatene"] for record in payload["result"]
        }
        # The out-of-window record (2026-07-10) is dropped; in-window and
        # boundary-day records are kept.
        self.assertEqual(ids, {"26-000123", "26-000789", "26-000999"})
        self.assertIn("dateDebut=2026-08-01", opener.requested[0])
        # dateFin is exclusive, so the inclusive end day is sent +1 day.
        self.assertIn("dateFin=2026-08-07", opener.requested[0])

    def test_client_date_window_constrains_hits_payload(self) -> None:
        opener = FakeOpener((FIXTURES / "hits_payload.json").read_bytes())
        client = AmfOamClient(opener=opener, requests_per_second=1000)

        payload = client.fetch_payload(
            date(2026, 8, 1), date(2026, 8, 6), limit=100
        )

        rows = payload["hits"]["hits"]
        ids = {row["_source"]["numeroConcatene"] for row in rows}
        self.assertEqual(ids, {"26-000321", "26-000987"})

    def test_connector_drops_out_of_window_records(self) -> None:
        connector, _ = make_connector(
            (FIXTURES / "result_payload.json").read_bytes(),
            universe={"MC": LVMH_IDENTITY},
        )

        items = connector.collect(make_request(("MC",), {"MC": "fr"}))

        ids = {item.external_id for item in items}
        self.assertNotIn("26-000456", ids)


class AmfOamMatchingTests(unittest.TestCase):
    def test_match_by_company_name(self) -> None:
        connector, _ = make_connector(
            (FIXTURES / "result_payload.json").read_bytes(),
            universe={"MC": {"name": LVMH_IDENTITY["name"], "isin": ""}},
        )

        items = connector.collect(make_request(("MC",), {"MC": "fr"}))

        self.assertEqual(len(items), 2)

    def test_match_by_isin_when_name_differs(self) -> None:
        payload = {
            "result": [
                {
                    "numeroConcatene": "26-000777",
                    "datePublication": "2026-08-02T10:00:00+02:00",
                    "titre": "Declaration de transparence",
                    "typesDocument": ["Information reglementee"],
                    "societes": [{"raisonSociale": "HOLDING INCONNUE SAS"}],
                    "documents": [{"path": "2026/08/02/X-26-000777.pdf"}],
                    "isin": "FR0000121014",
                }
            ]
        }
        connector, _ = make_connector(
            json.dumps(payload).encode("utf-8"),
            universe={"MC": LVMH_IDENTITY},
        )

        items = connector.collect(make_request(("MC",), {"MC": "fr"}))

        self.assertEqual(len(items), 1)
        self.assertEqual(items[0].external_id, "26-000777")

    def test_ticker_only_never_matches(self) -> None:
        # The record mentions the ticker mnemonic "MC" but neither the
        # universe company name nor the ISIN; it must not match.
        payload = {
            "result": [
                {
                    "numeroConcatene": "26-000888",
                    "datePublication": "2026-08-03T09:00:00+02:00",
                    "titre": "MC mentionne dans un titre sans lien",
                    "typesDocument": ["Information reglementee"],
                    "societes": [{"raisonSociale": "SOCIETE SANS RAPPORT SA"}],
                    "documents": [{"path": "2026/08/03/MC-26-000888.pdf"}],
                }
            ]
        }
        connector, _ = make_connector(
            json.dumps(payload).encode("utf-8"),
            universe={"MC": LVMH_IDENTITY},
        )

        items = connector.collect(make_request(("MC",), {"MC": "fr"}))

        self.assertEqual(items, [])
        self.assertEqual(connector.last_errors, ())

    def test_ticker_without_universe_identity_records_error(self) -> None:
        connector, opener = make_connector(b"{}", universe={})

        items = connector.collect(make_request(("MC",), {"MC": "fr"}))

        self.assertEqual(items, [])
        self.assertEqual(
            connector.last_errors, (("MC", "no_universe_identity"),)
        )
        self.assertEqual(opener.requested, [])


if __name__ == "__main__":
    unittest.main()
