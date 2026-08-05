from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from investment_monitor import DARTCompanyResolver


class FakeCache:
    def __init__(self, mapping=None) -> None:
        self.mapping = mapping or {}

    def resolve(self, ticker: str):
        return self.mapping.get(ticker)


class DARTCompanyResolverTests(unittest.TestCase):
    def test_resolves_to_open_dart_identity(self) -> None:
        resolver = DARTCompanyResolver(
            cache=FakeCache(
                {"005930": ("00593000", "삼성전자", "005930")}
            )
        )

        identity = resolver.resolve("005930")

        self.assertEqual(identity["ticker"], "005930")
        self.assertEqual(identity["name"], "삼성전자")
        self.assertEqual(identity["cik"], "00593000")
        self.assertEqual(identity["exchange"], "KRX")
        self.assertEqual(identity["mapping_status"], "mapped")

    def test_unmapped_ticker_returns_none(self) -> None:
        resolver = DARTCompanyResolver(cache=FakeCache())
        self.assertIsNone(resolver.resolve("005930"))

    def test_offline_resolver_without_key_returns_none(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            resolver = DARTCompanyResolver.offline(
                Path(temporary_directory) / "corp.json"
            )

            self.assertIsNone(resolver.resolve("005930"))


if __name__ == "__main__":
    unittest.main()
