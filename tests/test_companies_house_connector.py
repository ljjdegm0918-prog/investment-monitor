from datetime import date, datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from investment_monitor import (
    CollectionRequest,
    CompaniesHouseConnector,
    CompaniesHouseRequestError,
)
from investment_monitor.sources.companies_house.company_cache import (
    CompanyNumberCache,
    number_cache_path,
)


def filing(
    *,
    transaction_id: str = "MzA1Mjc1NTk2OWFkaXF6a2N4",
    description: str = "Appointment of a director",
    filing_date: str = "2026-08-01",
    filing_type: str = "AP01",
) -> dict:
    return {
        "transaction_id": transaction_id,
        "description": description,
        "date": filing_date,
        "type": filing_type,
        "category": "officers",
        "links": {
            "document_metadata_url": (
                "https://api.company-information.service.gov.uk/company/"
                f"00102498/filing-history/{transaction_id}/document"
            )
        },
    }


class FakeClient:
    def __init__(self, records=None, error=None) -> None:
        self.records = records or []
        self.error = error
        self.calls: list = []

    def get_filing_history(self, company_number: str):
        self.calls.append(company_number)
        if self.error is not None:
            raise self.error
        return self.records


class FakeCache:
    def __init__(self, numbers=None) -> None:
        self.numbers = numbers or {}
        self.requests: list = []

    def number_for_ticker(self, ticker: str):
        self.requests.append(ticker)
        return self.numbers.get(ticker)


class CompaniesHouseConnectorTests(unittest.TestCase):
    def request(self, tickers, markets):
        return CollectionRequest(
            tickers=tickers,
            start_date=date(2026, 8, 1),
            end_date=date(2026, 8, 5),
            markets=markets,
        )

    def test_non_uk_markets_are_skipped_with_zero_http(self) -> None:
        client = FakeClient()
        cache = FakeCache()
        connector = CompaniesHouseConnector(client=client, cache=cache)

        items = connector.collect(
            self.request(("AAPL", "0700"), {"AAPL": "us", "0700": "hk"})
        )

        self.assertEqual(items, [])
        self.assertEqual(connector.last_errors, ())
        self.assertEqual(client.calls, [])
        self.assertEqual(cache.requests, [])

    def test_uk_without_company_number_is_skipped_silently(self) -> None:
        client = FakeClient()
        cache = FakeCache()
        connector = CompaniesHouseConnector(client=client, cache=cache)

        items = connector.collect(
            self.request(("ZZZZ",), {"ZZZZ": "uk"})
        )

        self.assertEqual(items, [])
        self.assertEqual(connector.last_errors, ())
        self.assertEqual(client.calls, [])
        self.assertEqual(cache.requests, ["ZZZZ"])

    def test_unverified_mapping_not_in_cache_is_not_collected(self) -> None:
        class ExplodingHistoryClient:
            def get_filing_history(self, company_number):
                raise AssertionError(
                    "unverified mapping must not fetch filing history"
                )

        connector = CompaniesHouseConnector(
            client=ExplodingHistoryClient(),
            cache=FakeCache(),
        )

        items = connector.collect(
            self.request(("SOMECO",), {"SOMECO": "uk"})
        )

        self.assertEqual(items, [])
        self.assertEqual(connector.last_errors, ())

    def test_collects_after_cache_age_would_have_expired_ttl(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            cache_path = Path(temporary_directory) / "numbers.json"
            cache = CompanyNumberCache(cache_path)
            cache.remember("SOMECO", "01234567")
            aged = CompanyNumberCache(
                cache_path,
                clock=lambda: 10**12,
            )
            client = FakeClient(records=[filing()])

            connector = CompaniesHouseConnector(
                client=client,
                cache=aged,
            )
            items = connector.collect(
                self.request(("SOMECO",), {"SOMECO": "uk"})
            )

            self.assertEqual(len(items), 1)
            self.assertEqual(client.calls, ["01234567"])

    def test_default_cache_path_matches_shared_helper(self) -> None:
        connector = CompaniesHouseConnector(
            client=FakeClient(),
            cache=None,
        )

        self.assertEqual(
            connector._cache._cache_path,
            number_cache_path(),
        )

    def test_uk_mapped_company_maps_filings(self) -> None:
        client = FakeClient(
            records=[
                filing(),
                filing(
                    transaction_id="OLD-1",
                    filing_date="2026-07-30",
                ),
            ]
        )
        cache = FakeCache({"VOD": "01833679"})
        connector = CompaniesHouseConnector(client=client, cache=cache)

        items = connector.collect(
            self.request(("VOD",), {"VOD": "uk"})
        )

        self.assertEqual(len(items), 1)
        first = items[0]
        self.assertEqual(first.source, "companies_house")
        self.assertEqual(first.source_type, "regulatory_filing")
        self.assertEqual(first.external_id, "MzA1Mjc1NTk2OWFkaXF6a2N4")
        self.assertEqual(first.tickers, ("VOD",))
        self.assertEqual(first.market, "uk")
        self.assertEqual(first.title, "Appointment of a director")
        self.assertEqual(first.document_type, "AP01")
        self.assertEqual(
            first.published_at,
            datetime(2026, 8, 1, 11, 0, tzinfo=timezone.utc),
        )
        self.assertIn("company/01833679/filing-history/MzA1Mjc1NTk2OWFkaXF6a2N4", first.url)
        self.assertEqual(first.raw_metadata["company_number"], "01833679")
        self.assertEqual(client.calls, ["01833679"])

    def test_network_failure_is_recorded_and_redacted(self) -> None:
        client = FakeClient(
            error=CompaniesHouseRequestError(
                "boom Authorization: Basic c2VjcmV0OnBhc3M=",
                status_code=500,
            )
        )
        cache = FakeCache({"VOD": "01833679"})
        connector = CompaniesHouseConnector(client=client, cache=cache)

        with self.assertRaises(CompaniesHouseRequestError):
            connector.collect(
                self.request(("VOD",), {"VOD": "uk"})
            )

        message = connector.last_errors[0][1]
        self.assertNotIn("c2VjcmV0", message)
        self.assertIn("Authorization: Basic REDACTED", message)

    def test_cache_seed_is_used_via_real_cache(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            cache = CompanyNumberCache(
                Path(temporary_directory) / "numbers.json"
            )
            client = FakeClient(records=[filing()])
            connector = CompaniesHouseConnector(client=client, cache=cache)

            items = connector.collect(
                self.request(("BP.",), {"BP.": "uk"})
            )

            self.assertEqual(len(items), 1)
            self.assertEqual(client.calls, ["00102498"])


if __name__ == "__main__":
    unittest.main()
