"""HU market foundation tests."""

from datetime import date, datetime, timezone
import unittest

from investment_monitor import (
    ALLOWED_MARKETS,
    CollectionRequest,
    InformationItem,
    MARKET_HU,
)
from investment_monitor.company_import import parse_company_inputs
from investment_monitor.web_repository import normalize_hu_ticker


class MarketHuTests(unittest.TestCase):
    def test_market_is_declared(self) -> None:
        self.assertEqual(MARKET_HU, "hu")
        self.assertIn("hu", ALLOWED_MARKETS)

    def test_collection_request_accepts_market(self) -> None:
        request = CollectionRequest(
            tickers=("OTP",),
            start_date=date(2026, 8, 1),
            end_date=date(2026, 8, 2),
            markets={"OTP": "hu"},
        )
        self.assertEqual(request.market_for("OTP"), "hu")

    def test_information_item_accepts_market(self) -> None:
        item = InformationItem(
            source="news",
            source_type="news",
            external_id="hu-1",
            tickers=("OTP",),
            issuer="OTP Bank",
            published_at=datetime(2026, 8, 1, tzinfo=timezone.utc),
            title="Hungary headline",
            document_type="news",
            url="https://example.test/hu-1",
            collected_at=datetime(2026, 8, 1, 12, tzinfo=timezone.utc),
            market="hu",
        )
        self.assertEqual(item.market, "hu")

    def test_normalize_strips_quote_suffix(self) -> None:
        for form in ("OTP.BU", "OTP.bu", "OTP BU", "OTP-BU", "OTP.BU.BU", "MOL.BU", "RICHTER.BU"):
            self.assertEqual(normalize_hu_ticker(form), form.split(".")[0].split(" ")[0].split("-")[0], form)

    def test_normalize_keeps_bare_suffix_word(self) -> None:
        self.assertEqual(normalize_hu_ticker("BU"), "BU")

    def test_normalize_keeps_isin(self) -> None:
        self.assertEqual(normalize_hu_ticker("HU0000061726"), "HU0000061726")

    def test_import_at_suffix_routes_to_market(self) -> None:
        parsed = parse_company_inputs("OTP@HU", "us")
        self.assertEqual(parsed[0].ticker, "OTP")
        self.assertEqual(parsed[0].market, "hu")
        parsed_dot = parse_company_inputs("OTP.BU", "us")
        self.assertEqual(parsed_dot[0].market, "hu")


if __name__ == "__main__":
    unittest.main()
