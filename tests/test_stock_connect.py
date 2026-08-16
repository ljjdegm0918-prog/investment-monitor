"""P5-1 Stock Connect mapping tests."""

import unittest

from investment_monitor.universe.stock_connect import (
    stock_connect_summary,
    stock_connect_venues_for,
)
from investment_monitor.universe.exchange_catalog import (
    list_countries,
    list_venues,
)


class StockConnectTests(unittest.TestCase):
    def test_cn_maps_to_two_connect_venues(self):
        rows = stock_connect_venues_for("cn")
        self.assertEqual(
            [row["venue_id"] for row in rows],
            ["SEHKSZSE", "SEHKSTAR"],
        )
        self.assertTrue(all(row["connect_direction"] == "northbound" for row in rows))

    def test_connect_venue_ids_exist_under_hk(self):
        hk_venue_ids = {
            row["venue_id"] for row in list_venues("HK")
        }
        self.assertTrue({"SEHKSZSE", "SEHKSTAR"} <= hk_venue_ids)

    def test_no_disclosure_connector_is_created(self):
        summary = stock_connect_summary()
        self.assertIsNone(summary["disclosure_connector"])
        self.assertIsNone(stock_connect_summary()["disclosure_connector"])
        extras = {
            row["country_code"]: row
            for row in list_countries(include_extra=True)
        }
        self.assertEqual(extras["CN"]["catalog_role"], "extra")

    def test_other_markets_have_no_connect_venues(self):
        for market in ("us", "hk", "jp"):
            self.assertEqual(stock_connect_venues_for(market), [])
        self.assertEqual(len(stock_connect_venues_for(" cn ")), 2)


if __name__ == "__main__":
    unittest.main()
