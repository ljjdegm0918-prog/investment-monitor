"""P0-0 exchange catalog contract tests."""

import unittest

from investment_monitor.universe.exchange_catalog import (
    catalog_summary,
    country_count,
    list_countries,
    list_venues,
    load_exchange_catalog,
    primary_exchanges_for,
    venue_count,
)


class ExchangeCatalogTests(unittest.TestCase):
    def test_frozen_counts_28_countries_87_venues(self):
        self.assertEqual(country_count(), 28)
        self.assertEqual(venue_count(), 87)
        summary = catalog_summary()
        self.assertEqual(summary["countries"], 28)
        self.assertEqual(summary["venues"], 87)

    def test_region_slices_match_plan(self):
        countries = {c["country_code"]: c for c in list_countries()}
        venues = list_venues()
        by_region: dict = {}
        for row in venues:
            by_region[row["region"]] = by_region.get(row["region"], 0) + 1
        self.assertEqual(by_region["Americas"], 31)
        self.assertEqual(by_region["Europe"], 44)
        self.assertEqual(by_region["Asia"], 12)
        self.assertEqual(
            sum(c["region"] == "Americas" for c in countries.values()), 3
        )
        self.assertEqual(
            sum(c["region"] == "Europe" for c in countries.values()), 19
        )
        self.assertEqual(
            sum(c["region"] == "Asia" for c in countries.values()), 6
        )

    def test_country_and_venue_samples(self):
        countries = {c["country_code"]: c for c in list_countries()}
        self.assertEqual(countries["US"]["market_code"], "us")
        self.assertEqual(countries["MX"]["market_code"], "mx")
        self.assertEqual(countries["IN"]["market_code"], "in")
        self.assertEqual(countries["GB"]["market_code"], "uk")
        self.assertEqual(countries["RU"]["market_code"], None)
        self.assertEqual(countries["RU"]["trading_status"], "suspended")

        venue_ids = {row["venue_id"] for row in list_venues()}
        for sample in ("ARCA", "NYSE", "MEXI", "NSE", "MOEX", "IBIS",
                       "FWB", "TSE", "SEHK", "SGX", "TWSE", "VIRTX"):
            self.assertIn(sample, venue_ids, f"missing venue {sample}")

        self.assertEqual(venue_count("US"), 21)
        self.assertEqual(venue_count("CA"), 9)
        self.assertEqual(venue_count("MX"), 1)
        self.assertEqual(venue_count("IN"), 1)
        self.assertEqual(venue_count("JP"), 3)

    def test_extra_repo_markets_stay_out_of_denominator(self):
        extra = list_countries(include_extra=True)
        self.assertEqual(len(extra), 28 + 7)
        extras = {item["country_code"]: item for item in extra[28:]}
        self.assertEqual(extras["CN"]["catalog_role"], "extra")
        self.assertEqual(extras["KR"]["catalog_role"], "extra")
        self.assertEqual(extras["AQ"]["catalog_role"], "venue_only")
        self.assertEqual(extras["CXE"]["catalog_role"], "venue_only")
        self.assertEqual(extras["TRQ"]["catalog_role"], "venue_only")
        self.assertEqual(extras["EUX"]["catalog_role"], "out_of_scope")
        self.assertEqual(extras["EMF"]["catalog_role"], "out_of_scope")

    def test_venue_contract_fields(self):
        for row in list_venues():
            for field in (
                "venue_id", "venue_name", "ibkr_label", "country_code",
                "market_code", "region", "venue_role", "instrument_type",
                "valid_exchanges",
            ):
                self.assertIn(field, row, f"venue {row} missing {field}")
        primary = primary_exchanges_for("DE")
        self.assertTrue({"IBIS", "FWB"} <= set(primary))

    def test_load_returns_seed_mapping(self):
        catalog = load_exchange_catalog()
        self.assertEqual(catalog["schema_version"], 2)
        self.assertIn("normalization", catalog)
        self.assertEqual(catalog["normalization"]["etf_columns"]["total"], 27)


if __name__ == "__main__":
    unittest.main()
