'''LV market foundation tests.'''
from datetime import date, datetime, timezone
import unittest

from investment_monitor import (
    ALLOWED_MARKETS,
    CollectionRequest,
    InformationItem,
)
from investment_monitor.company_import import parse_company_inputs
from investment_monitor.web_repository import (
    normalize_lv_ticker as normalize_ticker,
)

MARKET = "lv"


class MarketLvTests(unittest.TestCase):
    def test_market_is_declared(self) -> None:
        self.assertIn(MARKET, ALLOWED_MARKETS)

    def test_collection_request_accepts_market(self) -> None:
        request = CollectionRequest(
            tickers=("SAF1R",),
            start_date=date(2026, 8, 1),
            end_date=date(2026, 8, 2),
            markets={"SAF1R": MARKET},
        )
        self.assertEqual(request.market_for("SAF1R"), MARKET)

    def test_information_item_accepts_market(self) -> None:
        item = InformationItem(
            source="news",
            source_type="news",
            external_id="lv-1",
            tickers=("SAF1R",),
            issuer="SAF1R",
            published_at=datetime(2026, 8, 1, tzinfo=timezone.utc),
            title="Baltic headline",
            document_type="news",
            url="https://example.test/lv-1",
            collected_at=datetime(2026, 8, 1, 12, tzinfo=timezone.utc),
            market=MARKET,
        )
        self.assertEqual(item.market, MARKET)

    def test_normalize_strips_quote_suffix(self) -> None:
        for form in (
            "SAF1R.RG",
            "SAF1R.rg",
            "SAF1R RG",
            "SAF1R-RG",
            "SAF1R.RG.RG",
        ):
            self.assertEqual(normalize_ticker(form), "SAF1R", form)

    def test_normalize_keeps_bare_suffix_word(self) -> None:
        self.assertEqual(normalize_ticker("RG"), "RG")

    def test_normalize_keeps_isin(self) -> None:
        self.assertEqual(normalize_ticker("LV0000100808"), "LV0000100808")

    def test_import_at_suffix_routes_to_market(self) -> None:
        parsed = parse_company_inputs("SAF1R@LV", "us")
        self.assertEqual(parsed[0].ticker, "SAF1R")
        self.assertEqual(parsed[0].market, MARKET)
        parsed_dot = parse_company_inputs("SAF1R.RG", "us")
        self.assertEqual(parsed_dot[0].market, MARKET)


if __name__ == "__main__":
    unittest.main()
