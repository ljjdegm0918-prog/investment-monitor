from datetime import date, datetime, timezone
from pathlib import Path
import unittest

from investment_monitor import (
    CollectionRequest,
    CnmvHrClient,
    CnmvHrConnector,
    CnmvHrDataError,
    CnmvHrRequestError,
)
from investment_monitor.registry import create_default_registry
from investment_monitor.sources.cnmv_hr.matcher import (
    CnmvHrCompanyMatcher,
    company_names_match,
)
from zoneinfo import ZoneInfo


FIXTURES = Path(__file__).parent / "fixtures" / "cnmv_hr"


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
    def __init__(self, fixtures: dict) -> None:
        self.fixtures = fixtures
        self.requested: list = []

    def __call__(self, request, timeout=None):
        url = request.full_url
        self.requested.append(url)
        for marker, body in self.fixtures.items():
            if marker in url:
                return FakeResponse(body)
        raise AssertionError(f"unexpected url: {url}")


def oir_opener(**overrides):
    fixtures = {
        "informacion-privilegiada": (FIXTURES / "cnmv_ip.xml").read_bytes(),
        "Otra-Informacion-Relevante": (FIXTURES / "cnmv_oir.xml").read_bytes(),
    }
    fixtures.update(overrides)
    return FakeOpener(fixtures)


def make_client(opener):
    return CnmvHrClient(opener=opener, requests_per_second=1000)


class CnmvHrClientTests(unittest.TestCase):
    def test_parses_records_and_filters_madrid_window(self) -> None:
        opener = oir_opener()
        client = make_client(opener)

        records = client.fetch_disclosures(
            date(2026, 8, 1),
            date(2026, 8, 8),
        )

        self.assertEqual(len(records), 3)
        self.assertEqual(opener.requested[0].count("RSS.asmx/GetNoticiasCNMV"), 1)
        santander = next(
            record
            for record in records
            if record["nreg"] == "42390"
        )
        self.assertEqual(
            santander["company_name"],
            "BANCO SANTANDER, S.A.",
        )
        self.assertEqual(
            santander["published"],
            datetime(2026, 8, 7, 15, 41, 40, tzinfo=timezone.utc),
        )
        self.assertEqual(
            santander["effective"],
            datetime(
                2026, 8, 7, 17, 41, tzinfo=ZoneInfo("Europe/Madrid")
            ),
        )
        self.assertEqual(
            santander["category"],
            "Sobre negocio y situacion financiera",
        )
        self.assertEqual(
            santander["text"],
            "Resultados del primer semestre de 2026.",
        )

    def test_empty_feeds_return_empty_list(self) -> None:
        client = make_client(oir_opener())
        empty = b'<?xml version="1.0"?><rss version="2.0"><Channel/></rss>'
        client._ip_url = "https://example.invalid/ip"
        client._oir_url = "https://example.invalid/oir"
        client._opener = FakeOpener(
            {"example.invalid": empty}
        )

        records = client.fetch_disclosures(
            date(2026, 8, 1),
            date(2026, 8, 8),
        )

        self.assertEqual(records, [])

    def test_malformed_feeds_raise_data_error(self) -> None:
        client = make_client(
            oir_opener(
                **{
                    "informacion-privilegiada": b"<html>blocked</html>",
                    "Otra-Informacion-Relevante": b"<html>blocked</html>",
                }
            )
        )

        with self.assertRaises(CnmvHrDataError):
            client.fetch_disclosures(
                date(2026, 8, 1),
                date(2026, 8, 8),
            )

    def test_one_feed_failing_keeps_other_records(self) -> None:
        def failing_opener(request, timeout=None):
            raise CnmvHrRequestError("cnmv blocked")

        client = CnmvHrClient(
            opener=failing_opener,
            requests_per_second=1000,
        )

        # Both URLs fail -> request error.
        with self.assertRaises(CnmvHrRequestError):
            client.fetch_disclosures(
                date(2026, 8, 1),
                date(2026, 8, 6),
            )

        # IP fails, OIR works -> records survive.
        def partial_opener(request, timeout=None):
            if "Otra-Informacion-Relevante" in request.full_url:
                return FakeResponse(
                    (FIXTURES / "cnmv_oir.xml").read_bytes()
                )
            raise CnmvHrRequestError("ip blocked")

        client = CnmvHrClient(
            opener=partial_opener,
            requests_per_second=1000,
        )
        records = client.fetch_disclosures(
            date(2026, 8, 1),
            date(2026, 8, 8),
        )
        self.assertEqual(len(records), 3)


class CnmvHrMatcherTests(unittest.TestCase):
    def test_ticker_short_name_never_matches_full_company_name(self) -> None:
        self.assertFalse(
            company_names_match("SAN", "BANCO SANTANDER, S.A.")
        )

    def test_legal_suffixes_are_stripped_on_both_sides(self) -> None:
        self.assertTrue(
            company_names_match(
                "BANCO SANTANDER",
                "BANCO SANTANDER, S.A.",
            )
        )
        self.assertTrue(
            company_names_match(
                "BANCO SANTANDER, S.A.",
                "BANCO SANTANDER",
            )
        )

    def test_matcher_uses_isin_when_present(self) -> None:
        matcher = CnmvHrCompanyMatcher()
        record = {
            "company_name": "BANCO SANTANDER, S.A.",
            "url": "https://www.cnmv.es/...?nreg=42390",
            "raw": {"isin": "ES0113900J37"},
        }

        self.assertTrue(
            matcher.matches(
                record,
                name="",
                isin="ES0113900J37",
            )
        )


class CnmvHrConnectorTests(unittest.TestCase):
    def request(self, tickers, markets):
        return CollectionRequest(
            tickers=tickers,
            start_date=date(2026, 8, 1),
            end_date=date(2026, 8, 8),
            markets=markets,
        )

    def make_connector(self, universe=None):
        connector = CnmvHrConnector(
            client=make_client(oir_opener()),
            universe=universe,
        )
        return connector

    def test_non_es_markets_are_skipped_with_zero_http(self) -> None:
        opener = oir_opener()
        connector = CnmvHrConnector(
            client=make_client(opener),
            universe={},
        )

        items = connector.collect(
            self.request(("AAPL", "VOD"), {"AAPL": "us", "VOD": "uk"})
        )

        self.assertEqual(items, [])
        self.assertEqual(connector.last_errors, ())
        self.assertEqual(opener.requested, [])

    def test_es_without_universe_identity_is_skipped_honestly(self) -> None:
        opener = oir_opener()
        connector = CnmvHrConnector(
            client=make_client(opener),
            universe={},
        )

        items = connector.collect(
            self.request(("SAN",), {"SAN": "es"})
        )

        self.assertEqual(items, [])
        self.assertEqual(opener.requested, [])
        self.assertEqual(
            connector.last_errors,
            (("SAN", "no_universe_identity"),),
        )

    def test_es_universe_name_matches_records(self) -> None:
        connector = self.make_connector(
            universe={
                "SAN": {
                    "name": "BANCO SANTANDER, S.A.",
                    "exchange": "BME (SIBE)",
                    "isin": "ES0113900J37",
                }
            }
        )

        items = connector.collect(
            self.request(("SAN.MC",), {"SAN.MC": "es"})
        )

        self.assertEqual(len(items), 1)
        first = items[0]
        self.assertEqual(first.source, "cnmv_hr")
        self.assertEqual(first.source_type, "regulatory_filing")
        self.assertEqual(first.tickers, ("SAN",))
        self.assertEqual(first.market, "es")
        self.assertEqual(first.external_id, "42390")
        self.assertEqual(first.document_type, "Sobre negocio y situacion financiera")
        self.assertEqual(
            first.raw_metadata["provider"],
            "cnmv_rss",
        )
        self.assertEqual(first.raw_metadata["document_id"], "42390")
        self.assertIn("BANCO SANTANDER", first.title)

    def test_single_ticker_failure_raises_and_records_error(self) -> None:
        def failing_opener(request, timeout=None):
            raise CnmvHrRequestError("cnmv blocked")

        connector = CnmvHrConnector(
            client=CnmvHrClient(
                opener=failing_opener,
                requests_per_second=1000,
            ),
            universe={
                "SAN": {
                    "name": "BANCO SANTANDER, S.A.",
                    "isin": "ES0113900J37",
                }
            },
        )

        with self.assertRaises(CnmvHrRequestError):
            connector.collect(self.request(("SAN",), {"SAN": "es"}))

        self.assertEqual(len(connector.last_errors), 1)
        self.assertEqual(connector.last_errors[0][0], "SAN")

    def test_registry_registers_cnmv_hr_without_secret_field(self) -> None:
        registry = create_default_registry()

        self.assertIsNotNone(registry.factory_for("cnmv_hr"))
        self.assertEqual(registry.secret_fields_for("cnmv_hr"), ())


if __name__ == "__main__":
    unittest.main()
