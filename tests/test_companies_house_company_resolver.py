from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from investment_monitor import (
    CompaniesHouseCompanyResolver,
    CompaniesHouseRequestError,
    SQLiteInformationRepository,
    WebRepository,
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

    def test_unique_active_search_match_is_unverified_not_remembered(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            cache_path = Path(temporary_directory) / "numbers.json"
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
                cache_path,
            )

            identity = resolver.resolve("SOMECO")

        self.assertEqual(identity["cik"], "01234567")
        self.assertEqual(identity["mapping_status"], "unverified")
        self.assertEqual(identity["exchange"], "Unverified")
        self.assertIn("SOMECO", client.search_calls)
        self.assertIsNone(CompanyNumberCache(cache_path).number_for_ticker("SOMECO"))

    def test_seed_ticker_is_remembered_in_trusted_cache(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            cache_path = Path(temporary_directory) / "numbers.json"
            client = FakeClient(
                companies={
                    "01833679": {
                        "company_name": "VODAFONE GROUP PUBLIC LIMITED COMPANY",
                        "company_number": "01833679",
                    }
                }
            )
            resolver = make_resolver(client, cache_path)

            identity = resolver.resolve("VOD")
            trusted = CompanyNumberCache(cache_path).number_for_ticker("VOD")

        self.assertEqual(identity["mapping_status"], "mapped")
        self.assertEqual(identity["exchange"], "LSE")
        self.assertEqual(trusted, "01833679")

    def test_numeric_input_is_remembered_in_trusted_cache(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            cache_path = Path(temporary_directory) / "numbers.json"
            client = FakeClient(
                companies={
                    "00048839": {
                        "company_name": "BARCLAYS PLC",
                        "company_number": "00048839",
                    }
                }
            )
            resolver = make_resolver(client, cache_path)

            identity = resolver.resolve("00048839")
            trusted = CompanyNumberCache(cache_path).number_for_ticker(
                "00048839"
            )

        self.assertEqual(identity["mapping_status"], "mapped")
        self.assertEqual(trusted, "00048839")

    def test_confirm_promotes_candidate_to_mapped_and_trusts_cache(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            cache_path = Path(temporary_directory) / "numbers.json"
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
            resolver = make_resolver(client, cache_path)
            candidate = resolver.resolve("SOMECO")
            self.assertEqual(candidate["mapping_status"], "unverified")
            self.assertIsNone(
                CompanyNumberCache(cache_path).number_for_ticker("SOMECO")
            )

            identity = resolver.confirm(
                "SOMECO",
                company_number="01234567",
            )
            trusted = CompanyNumberCache(cache_path).number_for_ticker(
                "SOMECO"
            )

        self.assertEqual(identity["mapping_status"], "mapped")
        self.assertEqual(identity["exchange"], "LSE")
        self.assertEqual(identity["cik"], "01234567")
        self.assertEqual(trusted, "01234567")

    def test_confirm_with_bad_number_keeps_unverified(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            client = FakeClient(companies={})
            resolver = make_resolver(
                client,
                Path(temporary_directory) / "numbers.json",
            )

            identity = resolver.confirm("SOMECO", company_number="99999999")

        self.assertIsNone(identity)

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


class CompaniesHouseRevalidationTests(unittest.TestCase):
    def make_repository_and_cache(self, temporary_directory):
        database_path = Path(temporary_directory) / "web.sqlite3"
        cache_path = Path(temporary_directory) / "numbers.json"
        SQLiteInformationRepository(database_path)
        repository = WebRepository(database_path)
        cache = CompanyNumberCache(cache_path)
        return repository, cache, cache_path

    def test_seed_mapping_stays_mapped_and_trusted(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            repository, cache, cache_path = self.make_repository_and_cache(
                temporary_directory
            )
            repository.set_company_mapping(
                {
                    "ticker": "VOD",
                    "name": "VODAFONE GROUP",
                    "exchange": "LSE",
                    "cik": "01833679",
                    "mapping_status": "mapped",
                },
                market="uk",
            )
            resolver = CompaniesHouseCompanyResolver(
                client=None,
                cache=cache,
            )

            changed = resolver.revalidate_legacy(
                repository,
                sentinel_path=Path(temporary_directory) / "scrub.sentinel",
            )
            companies = {
                company["ticker"]: company
                for company in repository.companies()
            }
            trusted = CompanyNumberCache(cache_path).number_for_ticker("VOD")

        self.assertEqual(changed, 0)
        self.assertEqual(companies["VOD"]["mapping_status"], "mapped")
        self.assertEqual(trusted, "01833679")

    def test_legacy_unique_mapping_downgrades_to_unverified_and_untrusts(
        self,
    ) -> None:
        with TemporaryDirectory() as temporary_directory:
            repository, cache, cache_path = self.make_repository_and_cache(
                temporary_directory
            )
            repository.set_company_mapping(
                {
                    "ticker": "SOMECO",
                    "name": "EXAMPLE CO PLC",
                    "exchange": "LSE",
                    "cik": "01234567",
                    "mapping_status": "mapped",
                },
                market="uk",
            )
            cache.remember("SOMECO", "01234567")
            resolver = CompaniesHouseCompanyResolver(
                client=None,
                cache=cache,
            )

            changed = resolver.revalidate_legacy(
                repository,
                sentinel_path=Path(temporary_directory) / "scrub.sentinel",
            )
            companies = {
                company["ticker"]: company
                for company in repository.companies()
            }
            trusted = CompanyNumberCache(cache_path).number_for_ticker(
                "SOMECO"
            )

        self.assertEqual(changed, 1)
        self.assertEqual(companies["SOMECO"]["mapping_status"], "unverified")
        self.assertIsNone(trusted)

    def test_numeric_ticker_matching_cik_stays_mapped(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            repository, cache, cache_path = self.make_repository_and_cache(
                temporary_directory
            )
            repository.set_company_mapping(
                {
                    "ticker": "01234567",
                    "name": "EXAMPLE CO PLC",
                    "exchange": "LSE",
                    "cik": "01234567",
                    "mapping_status": "mapped",
                },
                market="uk",
            )
            resolver = CompaniesHouseCompanyResolver(
                client=None,
                cache=cache,
            )

            changed = resolver.revalidate_legacy(
                repository,
                sentinel_path=Path(temporary_directory) / "scrub.sentinel",
            )
            companies = {
                company["ticker"]: company
                for company in repository.companies()
            }
            trusted = CompanyNumberCache(cache_path).number_for_ticker(
                "01234567"
            )

        self.assertEqual(changed, 0)
        self.assertEqual(companies["01234567"]["mapping_status"], "mapped")
        self.assertEqual(trusted, "01234567")

    def test_confirmed_mapping_survives_second_revalidation(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            repository, cache, cache_path = self.make_repository_and_cache(
                temporary_directory
            )
            sentinel = Path(temporary_directory) / "scrub.sentinel"
            sentinel.write_text("done", encoding="utf-8")
            repository.set_company_mapping(
                {
                    "ticker": "SOMECO",
                    "name": "EXAMPLE CO PLC",
                    "exchange": "Unverified",
                    "cik": "01234567",
                    "mapping_status": "unverified",
                },
                market="uk",
            )
            client = FakeClient(
                companies={
                    "01234567": {
                        "company_name": "EXAMPLE CO PLC",
                        "company_number": "01234567",
                    }
                }
            )
            resolver = CompaniesHouseCompanyResolver(
                client=client,
                cache=cache,
            )
            identity = resolver.confirm(
                "SOMECO",
                company_number="01234567",
            )
            self.assertEqual(identity["mapping_status"], "mapped")
            repository.set_company_mapping(identity, market="uk")

            changed = resolver.revalidate_legacy(
                repository,
                sentinel_path=sentinel,
            )
            companies = {
                company["ticker"]: company
                for company in repository.companies()
            }
            trusted = CompanyNumberCache(cache_path).number_for_ticker(
                "SOMECO"
            )
            changed_again = resolver.revalidate_legacy(
                repository,
                sentinel_path=sentinel,
            )
            companies_again = {
                company["ticker"]: company
                for company in repository.companies()
            }

        self.assertEqual(changed, 0)
        self.assertEqual(companies["SOMECO"]["mapping_status"], "mapped")
        self.assertEqual(trusted, "01234567")
        self.assertEqual(changed_again, 0)
        self.assertEqual(
            companies_again["SOMECO"]["mapping_status"],
            "mapped",
        )

    def test_first_scrub_downgrades_legacy_unique_and_writes_sentinel(
        self,
    ) -> None:
        with TemporaryDirectory() as temporary_directory:
            repository, cache, cache_path = self.make_repository_and_cache(
                temporary_directory
            )
            sentinel = Path(temporary_directory) / "scrub.sentinel"
            self.assertFalse(sentinel.exists())
            repository.set_company_mapping(
                {
                    "ticker": "SOMECO",
                    "name": "EXAMPLE CO PLC",
                    "exchange": "LSE",
                    "cik": "01234567",
                    "mapping_status": "mapped",
                },
                market="uk",
            )
            cache.remember("SOMECO", "01234567")
            resolver = CompaniesHouseCompanyResolver(
                client=None,
                cache=cache,
            )

            changed = resolver.revalidate_legacy(
                repository,
                sentinel_path=sentinel,
            )
            companies = {
                company["ticker"]: company
                for company in repository.companies()
            }
            trusted = CompanyNumberCache(cache_path).number_for_ticker(
                "SOMECO"
            )
            sentinel_written = sentinel.exists()

        self.assertEqual(changed, 1)
        self.assertEqual(companies["SOMECO"]["mapping_status"], "unverified")
        self.assertIsNone(trusted)
        self.assertTrue(sentinel_written)

    def test_steady_state_mapped_without_trusted_cache_downgrades(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            repository, cache, cache_path = self.make_repository_and_cache(
                temporary_directory
            )
            sentinel = Path(temporary_directory) / "scrub.sentinel"
            sentinel.write_text("done", encoding="utf-8")
            repository.set_company_mapping(
                {
                    "ticker": "SOMECO",
                    "name": "EXAMPLE CO PLC",
                    "exchange": "LSE",
                    "cik": "01234567",
                    "mapping_status": "mapped",
                },
                market="uk",
            )
            resolver = CompaniesHouseCompanyResolver(
                client=None,
                cache=cache,
            )

            changed = resolver.revalidate_legacy(
                repository,
                sentinel_path=sentinel,
            )
            companies = {
                company["ticker"]: company
                for company in repository.companies()
            }
            trusted = CompanyNumberCache(cache_path).number_for_ticker(
                "SOMECO"
            )

        self.assertEqual(changed, 1)
        self.assertEqual(companies["SOMECO"]["mapping_status"], "unverified")
        self.assertIsNone(trusted)


if __name__ == "__main__":
    unittest.main()
