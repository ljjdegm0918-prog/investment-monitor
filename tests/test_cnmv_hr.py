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
from investment_monitor.sources.cnmv_hr import (
    CnmvHrFeedOutcome,
    CnmvHrFetchResult,
)
from investment_monitor.sources.cnmv_hr.connector import _map_records
from investment_monitor.sources.cnmv_hr.matcher import (
    CnmvHrCompanyMatcher,
    company_names_match,
)
from zoneinfo import ZoneInfo
from provenance_assertions import assert_official_provenance


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


class OutcomeOpener:
    def __init__(self, *, ip, oir) -> None:
        self.responses = {"ip": ip, "oir": oir}
        self.requested: list = []

    def __call__(self, request, timeout=None):
        url = request.full_url
        self.requested.append(url)
        feed_id = "oir" if "Otra-Informacion-Relevante" in url else "ip"
        response = self.responses[feed_id]
        if isinstance(response, Exception):
            raise response
        return FakeResponse(response)


def oir_opener(**overrides):
    fixtures = {
        "informacion-privilegiada": (FIXTURES / "cnmv_ip.xml").read_bytes(),
        "Otra-Informacion-Relevante": (FIXTURES / "cnmv_oir.xml").read_bytes(),
    }
    fixtures.update(overrides)
    return FakeOpener(fixtures)


def make_client(opener):
    return CnmvHrClient(opener=opener, requests_per_second=1000)


def empty_feed() -> bytes:
    return b'<?xml version="1.0"?><rss version="2.0"><Channel/></rss>'


def three_santander_records() -> bytes:
    body = (FIXTURES / "cnmv_oir.xml").read_bytes()
    return (
        body.replace(b"ACCIONA, S.A.", b"BANCO SANTANDER, S.A.")
        .replace(b"IZERTIS , S.A.", b"BANCO SANTANDER, S.A.")
    )


class CnmvHrClientTests(unittest.TestCase):
    def test_structured_result_keeps_ip_success_and_oir_failure(self) -> None:
        result = make_client(OutcomeOpener(
            ip=three_santander_records(),
            oir=CnmvHrRequestError("oir fixture blocked"),
        )).fetch_disclosures(date(2026, 8, 1), date(2026, 8, 8))

        self.assertIsInstance(result, CnmvHrFetchResult)
        self.assertEqual(len(result.records), 3)
        self.assertIsInstance(result.feed_outcomes, tuple)
        outcomes = {outcome.feed_id: outcome for outcome in result.feed_outcomes}
        self.assertEqual(set(outcomes), {"ip", "oir"})
        self.assertIsInstance(outcomes["ip"], CnmvHrFeedOutcome)
        self.assertEqual(outcomes["ip"].status, "success")
        self.assertEqual(outcomes["ip"].records_read, 3)
        self.assertIn("informacion-privilegiada", outcomes["ip"].retrieval_url)
        self.assertIsNotNone(outcomes["ip"].finished_at.tzinfo)
        self.assertIsNone(outcomes["ip"].error_kind)
        self.assertIsNone(outcomes["ip"].error_message)
        self.assertEqual(outcomes["oir"].status, "failure")
        self.assertEqual(outcomes["oir"].records_read, 0)
        self.assertIn("Otra-Informacion-Relevante", outcomes["oir"].retrieval_url)
        self.assertEqual(outcomes["oir"].error_kind, "request")
        self.assertIn("oir fixture blocked", outcomes["oir"].error_message)

    def test_structured_result_keeps_oir_success_and_ip_failure(self) -> None:
        result = make_client(OutcomeOpener(
            ip=CnmvHrDataError("ip malformed fixture"),
            oir=three_santander_records(),
        )).fetch_disclosures(date(2026, 8, 1), date(2026, 8, 8))

        self.assertEqual(len(result.records), 3)
        outcomes = {outcome.feed_id: outcome for outcome in result.feed_outcomes}
        self.assertEqual(outcomes["ip"].status, "failure")
        self.assertEqual(outcomes["ip"].error_kind, "data")
        self.assertIn("ip malformed fixture", outcomes["ip"].error_message)
        self.assertEqual(outcomes["oir"].status, "success")
        self.assertEqual(outcomes["oir"].records_read, 3)

    def test_structured_result_distinguishes_empty_partial_and_empty(self) -> None:
        partial = make_client(OutcomeOpener(
            ip=empty_feed(),
            oir=CnmvHrRequestError("oir fixture blocked"),
        )).fetch_disclosures(date(2026, 8, 1), date(2026, 8, 8))
        empty = make_client(OutcomeOpener(
            ip=empty_feed(),
            oir=empty_feed(),
        )).fetch_disclosures(date(2026, 8, 1), date(2026, 8, 8))

        self.assertEqual(partial.records, ())
        self.assertEqual(
            [(outcome.feed_id, outcome.status) for outcome in partial.feed_outcomes],
            [("ip", "empty"), ("oir", "failure")],
        )
        self.assertEqual(empty.records, ())
        self.assertEqual(
            [(outcome.feed_id, outcome.status) for outcome in empty.feed_outcomes],
            [("ip", "empty"), ("oir", "empty")],
        )

    def test_structured_result_retains_both_feed_failures(self) -> None:
        result = make_client(OutcomeOpener(
            ip=CnmvHrRequestError("ip fixture blocked"),
            oir=CnmvHrDataError("oir malformed fixture"),
        )).fetch_disclosures(date(2026, 8, 1), date(2026, 8, 8))

        self.assertEqual(result.records, ())
        self.assertEqual(
            [(outcome.feed_id, outcome.status) for outcome in result.feed_outcomes],
            [("ip", "failure"), ("oir", "failure")],
        )
        self.assertEqual(result.feed_outcomes[0].error_kind, "request")
        self.assertEqual(result.feed_outcomes[1].error_kind, "data")

    def test_parses_records_and_filters_madrid_window(self) -> None:
        opener = oir_opener()
        client = make_client(opener)

        records = client.fetch_disclosures(
            date(2026, 8, 1),
            date(2026, 8, 8),
        )

        self.assertEqual(len(records.records), 3)
        self.assertEqual(opener.requested[0].count("RSS.asmx/GetNoticiasCNMV"), 1)
        santander = next(
            record
            for record in records.records
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
        self.assertEqual(
            santander["raw_payload"],
            {
                "title": "BANCO SANTANDER, S.A.",
                "link": santander["url"],
                "guid": santander["url"],
                "pubDate": "Fri, 07 Aug 2026 15:41:40 GMT",
                "description": (
                    "<p><b>17:41  07/08/2026  </b> Sobre negocio y "
                    "situacion financiera<BR/><BR/>Resultados del primer "
                    "semestre de 2026.</p>"
                ),
            },
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

        self.assertEqual(records.records, ())
        self.assertTrue(all(
            outcome.status == "empty" for outcome in records.feed_outcomes
        ))

    def test_malformed_feeds_raise_data_error(self) -> None:
        client = make_client(
            oir_opener(
                **{
                    "informacion-privilegiada": b"<html>blocked</html>",
                    "Otra-Informacion-Relevante": b"<html>blocked</html>",
                }
            )
        )

        result = client.fetch_disclosures(
            date(2026, 8, 1),
            date(2026, 8, 8),
        )

        self.assertEqual(result.records, ())
        self.assertTrue(all(
            outcome.status == "failure" for outcome in result.feed_outcomes
        ))

    def test_one_feed_failing_keeps_other_records(self) -> None:
        def failing_opener(request, timeout=None):
            raise CnmvHrRequestError("cnmv blocked")

        client = CnmvHrClient(
            opener=failing_opener,
            requests_per_second=1000,
        )

        # Both URLs fail -> both failures stay structured.
        failed = client.fetch_disclosures(
            date(2026, 8, 1),
            date(2026, 8, 6),
        )
        self.assertEqual(failed.records, ())
        self.assertTrue(all(
            outcome.status == "failure" for outcome in failed.feed_outcomes
        ))

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
        self.assertEqual(len(records.records), 3)
        self.assertEqual(
            [outcome.status for outcome in records.feed_outcomes],
            ["failure", "success"],
        )


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
        source_record = next(
            record
            for record in make_client(oir_opener()).fetch_disclosures(
                date(2026, 8, 1), date(2026, 8, 8)
            ).records
            if record["nreg"] == "42390"
        )
        assert_official_provenance(
            self,
            first,
            expected_payload=source_record["raw_payload"],
            official_source_id="42390",
            official_source_url=source_record["url"],
            retrieval_url=source_record["retrieval_url"],
            raw_payload_format="rss_xml_item",
            classification_code=None,
            classification_label=source_record["category"],
            published_at_raw=source_record["published_at_raw"],
            published_timezone="GMT",
        )

    def test_missing_nreg_is_not_guessed_for_official_source_id(self) -> None:
        raw_payload = {
            "title": "BANCO SANTANDER, S.A.",
            "link": "https://www.cnmv.es/notice-without-registration-number",
            "guid": "official-guid-without-registration-number",
            "pubDate": "Fri, 07 Aug 2026 15:41:40 GMT",
            "description": "<p>Fixture notice.</p>",
        }
        record = {
            "external_id": "official-guid-without-registration-number",
            "nreg": "",
            "company_name": "BANCO SANTANDER, S.A.",
            "published": datetime(2026, 8, 7, 15, 41, 40, tzinfo=timezone.utc),
            "effective": datetime(2026, 8, 7, 17, 41, tzinfo=ZoneInfo("Europe/Madrid")),
            "category": "Otra informacion relevante",
            "text": "Fixture notice.",
            "url": raw_payload["link"],
            "retrieval_url": "https://www.cnmv.es/fixture-feed",
            "published_at_raw": raw_payload["pubDate"],
            "raw_payload": raw_payload,
        }

        item = _map_records(
            [record], ticker="SAN", collected_at=datetime.now(timezone.utc)
        )[0]

        assert_official_provenance(
            self,
            item,
            expected_payload=raw_payload,
            official_source_id=None,
            official_source_url=raw_payload["link"],
            retrieval_url=record["retrieval_url"],
            raw_payload_format="rss_xml_item",
            classification_code=None,
            classification_label=record["category"],
            published_at_raw=raw_payload["pubDate"],
            published_timezone="GMT",
        )

    def test_single_ticker_both_feed_failures_are_recorded(self) -> None:
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

        items = connector.collect(self.request(("SAN",), {"SAN": "es"}))

        self.assertEqual(items, [])
        self.assertEqual(len(connector.last_errors), 1)
        self.assertEqual(connector.last_errors[0][0], "SAN")
        self.assertIn("ip", connector.last_errors[0][1].lower())
        self.assertIn("oir", connector.last_errors[0][1].lower())

    def test_registry_registers_cnmv_hr_without_secret_field(self) -> None:
        registry = create_default_registry()

        self.assertIsNotNone(registry.factory_for("cnmv_hr"))
        self.assertEqual(registry.secret_fields_for("cnmv_hr"), ())


if __name__ == "__main__":
    unittest.main()
