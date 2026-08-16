"""IN market foundation tests."""

from datetime import date, datetime, timezone
import unittest

from investment_monitor import (
    ALLOWED_MARKETS,
    CollectionRequest,
    InformationItem,
    MARKET_IN,
)
from investment_monitor.company_import import parse_company_inputs
from investment_monitor.web_repository import normalize_in_ticker


class MarketInTests(unittest.TestCase):
    def test_market_is_declared(self) -> None:
        self.assertEqual(MARKET_IN, "in")
        self.assertIn("in", ALLOWED_MARKETS)

    def test_collection_request_accepts_market(self) -> None:
        request = CollectionRequest(
            tickers=("RELIANCE",),
            start_date=date(2026, 8, 1),
            end_date=date(2026, 8, 2),
            markets={"RELIANCE": "in"},
        )
        self.assertEqual(request.market_for("RELIANCE"), "in")

    def test_information_item_accepts_market(self) -> None:
        item = InformationItem(
            source="news",
            source_type="news",
            external_id="in-1",
            tickers=("RELIANCE",),
            issuer="Reliance",
            published_at=datetime(2026, 8, 1, tzinfo=timezone.utc),
            title="India headline",
            document_type="news",
            url="https://example.test/in-1",
            collected_at=datetime(2026, 8, 1, 12, tzinfo=timezone.utc),
            market="in",
        )
        self.assertEqual(item.market, "in")

    def test_normalize_strips_quote_suffix(self) -> None:
        for form in ("RELIANCE.NS", "RELIANCE.ns", "RELIANCE NS", "RELIANCE-NS", "RELIANCE.BO", "RELIANCE.BO.BO"):
            self.assertEqual(normalize_in_ticker(form), "RELIANCE", form)

    def test_normalize_keeps_bare_suffix_word(self) -> None:
        self.assertEqual(normalize_in_ticker("NS"), "NS")
        self.assertEqual(normalize_in_ticker("BO"), "BO")

    def test_normalize_keeps_isin(self) -> None:
        self.assertEqual(normalize_in_ticker("INE002A01018"), "INE002A01018")

    def test_import_at_suffix_routes_to_market(self) -> None:
        parsed = parse_company_inputs("RELIANCE@IN", "us")
        self.assertEqual(parsed[0].ticker, "RELIANCE")
        self.assertEqual(parsed[0].market, "in")
        parsed_dot = parse_company_inputs("RELIANCE.NS", "us")
        self.assertEqual(parsed_dot[0].market, "in")


if __name__ == "__main__":
    unittest.main()
