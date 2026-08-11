from datetime import date, datetime, timezone
import json
from pathlib import Path
import unittest

from investment_monitor import (
    CollectionRequest,
    BmeRelevantFactsClient,
    BmeRelevantFactsConnector,
    BmeRelevantFactsDataError,
    BmeRelevantFactsRequestError,
)
from investment_monitor.registry import create_default_registry
from zoneinfo import ZoneInfo
from provenance_assertions import assert_official_provenance


FIXTURES = Path(__file__).parent / "fixtures" / "bme_relevant_facts"
MADRID = ZoneInfo("Europe/Madrid")


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


def make_client(opener):
    return BmeRelevantFactsClient(opener=opener, requests_per_second=1000)


class BmeRelevantFactsClientTests(unittest.TestCase):
    def test_confirmed_more_results_at_page_limit_raises_truncation(self) -> None:
        body = json.loads((FIXTURES / "san_facts.json").read_text(encoding="utf-8"))
        template = body["data"][0]
        body["data"] = [
            dict(template, cnmvRegNumber=f"OI{index:010d}")
            for index in range(50)
        ]
        body["totalResults"] = 51
        body["hasMoreResults"] = True
        opener = FakeOpener(json.dumps(body).encode("utf-8"))

        with self.assertRaises(BmeRelevantFactsDataError):
            make_client(opener).fetch_by_company(
                "13900",
                date(2026, 8, 1),
                date(2026, 8, 8),
                max_pages=1,
            )

        self.assertEqual(len(opener.requested), 1)

    def test_full_final_page_without_more_results_is_not_truncation(self) -> None:
        body = json.loads((FIXTURES / "san_facts.json").read_text(encoding="utf-8"))
        template = body["data"][0]
        body["data"] = [
            dict(template, cnmvRegNumber=f"OI{index:010d}")
            for index in range(50)
        ]
        body["totalResults"] = 50
        body["hasMoreResults"] = False
        opener = FakeOpener(json.dumps(body).encode("utf-8"))

        records = make_client(opener).fetch_by_company(
            "13900",
            date(2026, 8, 1),
            date(2026, 8, 8),
            max_pages=1,
        )

        self.assertEqual(len(records), 50)
        self.assertEqual(len(opener.requested), 1)

    def test_parses_records_and_filters_window(self) -> None:
        body = (FIXTURES / "san_facts.json").read_bytes()
        opener = FakeOpener(body)
        client = make_client(opener)

        records = client.fetch_by_company(
            "13900",
            date(2026, 8, 1),
            date(2026, 8, 8),
        )

        self.assertEqual(len(records), 2)
        self.assertIn("companyKey=13900", opener.requested[0])
        self.assertIn("from=20260801", opener.requested[0])
        self.assertIn("to=20260808", opener.requested[0])
        oi = next(
            record for record in records
            if record["external_id"] == "OI:42373"
        )
        self.assertEqual(oi["day"], date(2026, 8, 6))
        self.assertEqual(oi["title"], "Programas de recompra de acciones, estabilizacion y autocartera")
        self.assertEqual(
            oi["url"],
            "https://www.cnmv.es/Portal/Otra-Informacion-Relevante/"
            "Resultado-OIR.aspx?nreg=42373",
        )
        ip = next(
            record for record in records
            if record["external_id"] == "IP:3290"
        )
        self.assertEqual(
            ip["url"],
            "https://www.cnmv.es/Portal/Informacion-privilegiada/"
            "Resultado-IP.aspx?nreg=3290",
        )

    def test_malformed_json_raises_data_error(self) -> None:
        client = make_client(FakeOpener(b"<html>blocked</html>"))

        with self.assertRaises(BmeRelevantFactsDataError):
            client.fetch_by_company(
                "13900",
                date(2026, 8, 1),
                date(2026, 8, 8),
            )


class BmeRelevantFactsConnectorTests(unittest.TestCase):
    def request(self, tickers, markets):
        return CollectionRequest(
            tickers=tickers,
            start_date=date(2026, 8, 1),
            end_date=date(2026, 8, 8),
            markets=markets,
        )

    def make_connector(self, universe=None):
        opener = FakeOpener((FIXTURES / "san_facts.json").read_bytes())
        connector = BmeRelevantFactsConnector(
            client=make_client(opener),
            universe=universe,
        )
        return connector, opener

    def test_non_es_markets_are_skipped_with_zero_http(self) -> None:
        connector, opener = self.make_connector()

        items = connector.collect(
            self.request(("AAPL", "VOD"), {"AAPL": "us", "VOD": "uk"})
        )

        self.assertEqual(items, [])
        self.assertEqual(connector.last_errors, ())
        self.assertEqual(opener.requested, [])

    def test_es_without_universe_company_key_is_skipped_honestly(self) -> None:
        connector, opener = self.make_connector(universe={})

        items = connector.collect(
            self.request(("SAN",), {"SAN": "es"})
        )

        self.assertEqual(items, [])
        self.assertEqual(opener.requested, [])
        self.assertEqual(
            connector.last_errors,
            (("SAN", "no_universe_company_key"),),
        )

    def test_es_universe_company_key_collects_records(self) -> None:
        connector, opener = self.make_connector(
            universe={
                "SAN": {
                    "name": "BANCO SANTANDER",
                    "exchange": "BME (SIBE)",
                    "isin": "ES0113900J37",
                    "company_key": "13900",
                }
            }
        )

        items = connector.collect(
            self.request(("SAN.MC",), {"SAN.MC": "es"})
        )

        self.assertEqual(len(items), 2)
        first = items[0]
        self.assertEqual(first.source, "bme_relevant_facts")
        self.assertEqual(first.source_type, "regulatory_filing")
        self.assertEqual(first.tickers, ("SAN",))
        self.assertEqual(first.market, "es")
        self.assertEqual(first.external_id, "OI:42373")
        self.assertEqual(first.document_type, "423")
        self.assertEqual(first.raw_metadata["provider"], "bme_relevant_facts_api")
        self.assertEqual(first.raw_metadata["date_only"], True)
        self.assertEqual(first.raw_metadata["calendar_date"], "2026-08-06")
        self.assertEqual(
            first.published_at,
            datetime(2026, 8, 6, 12, tzinfo=MADRID),
        )
        self.assertIn("companyKey=13900", opener.requested[0])
        payload = next(
            record
            for record in json.loads(
                (FIXTURES / "san_facts.json").read_text(encoding="utf-8")
            )["data"]
            if record["cnmvRegNumber"] == "OI0000042373"
        )
        assert_official_provenance(
            self,
            first,
            expected_payload=payload,
            official_source_id="OI0000042373",
            official_source_url=first.url,
            retrieval_url=opener.requested[0],
            raw_payload_format="json",
            classification_code=payload["relevantFactCode"],
            classification_label=None,
            published_at_raw=payload["relevantFactDate"],
            published_timezone="Europe/Madrid",
        )

    def test_single_ticker_failure_raises_and_records_error(self) -> None:
        def failing_opener(request, timeout=None):
            raise BmeRelevantFactsRequestError("bme blocked")

        connector = BmeRelevantFactsConnector(
            client=BmeRelevantFactsClient(
                opener=failing_opener,
                requests_per_second=1000,
            ),
            universe={
                "SAN": {
                    "name": "BANCO SANTANDER",
                    "isin": "ES0113900J37",
                    "company_key": "13900",
                }
            },
        )

        with self.assertRaises(BmeRelevantFactsRequestError):
            connector.collect(self.request(("SAN",), {"SAN": "es"}))

        self.assertEqual(len(connector.last_errors), 1)
        self.assertEqual(connector.last_errors[0][0], "SAN")

    def test_registry_registers_bme_relevant_facts_without_secret(self) -> None:
        registry = create_default_registry()

        self.assertIsNotNone(registry.factory_for("bme_relevant_facts"))
        self.assertEqual(
            registry.secret_fields_for("bme_relevant_facts"),
            (),
        )


if __name__ == "__main__":
    unittest.main()
