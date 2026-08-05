from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from investment_monitor import (
    CompaniesHouseCompanyResolver,
    CompaniesHouseRequestError,
)
from investment_monitor.sources.companies_house.company_cache import (
    CompanyNumberCache,
)


class FakeClient:
    def __init__(self, companies=None, search=None) -> None:
        self.companies = companies or {}
        self.search_results = search or {}
        self.company_calls: list = []
        self.search_calls: list = []

    def get_company(self, company_number: str):
        self.company_calls.append(company_number)
        if company_number in self.companies:
            return self.companies[company_number]
        raise CompaniesHouseRequestError(
            f"not found {company_number}",
            status_code=404,
        )

    def search_companies(self, query: str):
        self.search_calls.append(query)
        return self.search_results.get(query, [])


def make_resolver(client, cache_path: Path) -> CompaniesHouseCompanyResolver:
    return CompaniesHouseCompanyResolver(
        client=client,
        cache=CompanyNumberCache(cache_path),
    )


class CompaniesHouseCompanyResolverTests(unittest.TestCase):
    def test_seed_ticker_maps_after_profile_check(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            client = FakeClient(
                companies={
                    "00102498": {
                        "company_name": "BP P.L.C.",
                        "company_number": "00102498",
                    }
                }
            )
            resolver = make_resolver(
                client,
                Path(temporary_directory) / "numbers.json",
            )

            identity = resolver.resolve("BP.")

        self.assertEqual(identity["ticker"], "BP.")
        self.assertEqual(identity["name"], "BP P.L.C.")
        self.assertEqual(identity["cik"], "00102498")
        self.assertEqual(identity["exchange"], "LSE")
        self.assertEqual(identity["mapping_status"], "mapped")
        self.assertEqual(client.company_calls, ["00102498"])

    def test_numeric_company_number_input_maps(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            client = FakeClient(
                companies={
                    "00048839": {
                        "company_name": "BARCLAYS PLC",
                        "company_number": "00048839",
                    }
                }
            )
            resolver = make_resolver(
                client,
                Path(temporary_directory) / "numbers.json",
            )

            identity = resolver.resolve("00048839")

        self.assertEqual(identity["cik"], "00048839")

    def test_unique_active_search_match_maps(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            client = FakeClient(
                companies={
                    "01234567": {
                        "company_name": "EXAMPLE CO PLC",
                        "company_number": "01234567",
                    }
                },
                search={
                    "SOMECO": [
                        {
                            "company_number": "01234567",
                            "company_status": "active",
                        }
                    ]
                },
            )
            resolver = make_resolver(
                client,
                Path(temporary_directory) / "numbers.json",
            )

            identity = resolver.resolve("SOMECO")

        self.assertEqual(identity["cik"], "01234567")
        self.assertIn("SOMECO", client.search_calls)

    def test_multiple_search_matches_stay_unmapped(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            client = FakeClient(
                search={
                    "SOMECO": [
                        {"company_number": "01234567", "company_status": "active"},
                        {"company_number": "07654321", "company_status": "active"},
                    ]
                }
            )
            resolver = make_resolver(
                client,
                Path(temporary_directory) / "numbers.json",
            )

            self.assertIsNone(resolver.resolve("SOMECO"))
            self.assertEqual(client.company_calls, [])

    def test_unknown_ticker_returns_none(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            resolver = make_resolver(
                FakeClient(),
                Path(temporary_directory) / "numbers.json",
            )

            self.assertIsNone(resolver.resolve("ZZZZ"))

    def test_offline_resolver_returns_none_without_network(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            resolver = CompaniesHouseCompanyResolver.offline(
                Path(temporary_directory) / "numbers.json"
            )

            self.assertIsNone(resolver.resolve("BP."))


if __name__ == "__main__":
    unittest.main()
