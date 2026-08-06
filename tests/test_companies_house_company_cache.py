from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from investment_monitor import CompanyNumberCache
from investment_monitor.sources.companies_house.company_cache import (
    SEED_COMPANIES,
)


class CompanyNumberCacheTests(unittest.TestCase):
    def test_seed_table_contains_verified_blue_chips(self) -> None:
        self.assertEqual(SEED_COMPANIES["VOD"], "01833679")
        self.assertEqual(SEED_COMPANIES["BP."], "00102498")
        self.assertEqual(SEED_COMPANIES["SHEL"], "04366849")
        self.assertLessEqual(len(SEED_COMPANIES), 10)

    def test_numeric_inputs_are_zero_padded_to_eight(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            cache = CompanyNumberCache(
                Path(temporary_directory) / "numbers.json"
            )

            self.assertEqual(cache.number_for_ticker("123456"), "00123456")
            self.assertEqual(cache.number_for_ticker("1234567"), "01234567")
            self.assertEqual(cache.number_for_ticker("12345678"), "12345678")
            self.assertIsNone(cache.number_for_ticker("12345"))

    def test_seed_and_case_insensitive_lookup(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            cache = CompanyNumberCache(
                Path(temporary_directory) / "numbers.json"
            )

            self.assertEqual(cache.number_for_ticker("vod"), "01833679")
            self.assertEqual(cache.number_for_ticker("bp."), "00102498")
            self.assertIsNone(cache.number_for_ticker("ZZZZ"))

    def test_remembered_number_is_reused(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            cache_path = Path(temporary_directory) / "numbers.json"
            cache = CompanyNumberCache(cache_path)
            cache.remember("ZZZZ", "01234567")

            reopened = CompanyNumberCache(cache_path)
            self.assertEqual(reopened.number_for_ticker("zzzz"), "01234567")


if __name__ == "__main__":
    unittest.main()
