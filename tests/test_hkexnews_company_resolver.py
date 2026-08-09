import unittest

from investment_monitor.sources.hkexnews.company_resolver import (
    HKEXNewsCompanyResolver,
)


class FakeClient:
    def __init__(self, stock=None) -> None:
        self.stock = stock
        self.calls: list = []

    def stock_for(self, ticker):
        self.calls.append(ticker)
        return self.stock


class HKEXNewsCompanyResolverTests(unittest.TestCase):
    def test_resolve_maps_known_hk_stock_to_sehk(self) -> None:
        client = FakeClient(
            stock={
                "stock_id": "15157",
                "stock_name": "TENCENT",
                "stock_code": "00700",
            }
        )
        resolver = HKEXNewsCompanyResolver(client=client)

        mapping = resolver.resolve("0700.HK")

        self.assertEqual(mapping["ticker"], "00700")
        self.assertEqual(mapping["name"], "TENCENT")
        self.assertEqual(mapping["exchange"], "SEHK")
        self.assertEqual(mapping["cik"], "15157")
        self.assertEqual(mapping["mapping_status"], "mapped")

    def test_resolve_unknown_stock_returns_none(self) -> None:
        resolver = HKEXNewsCompanyResolver(client=FakeClient(stock=None))

        self.assertIsNone(resolver.resolve("99999"))


if __name__ == "__main__":
    unittest.main()
