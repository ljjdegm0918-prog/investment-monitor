"""AT market foundation tests."""

from datetime import date, datetime, timezone
import unittest

from investment_monitor import (
    ALLOWED_MARKETS,
    CollectionRequest,
    InformationItem,
    MARKET_AT,
)
from investment_monitor.company_import import parse_company_inputs
from investment_monitor.web_repository import normalize_at_ticker


class MarketAtTests(unittest.TestCase):
    def test_market_is_declared(self) -> None:
        self.assertEqual(MARKET_AT, "at")
        self.assertIn("at", ALLOWED_MARKETS)

    def test_collection_request_accepts_market(self) -> None:
        request = CollectionRequest(
            tickers=("VOE",),
            start_date=date(2026, 8, 1),
            end_date=date(2026, 8, 2),
            markets={"VOE": "at"},
        )
        self.assertEqual(request.market_for("VOE"), "at")

    def test_information_item_accepts_market(self) -> None:
        item = InformationItem(
            source="news",
            source_type="news",
            external_id="at-1",
            tickers=("VOE",),
            issuer="VOE",
            published_at=datetime(2026, 8, 1, tzinfo=timezone.utc),
            title="Vienna headline",
            document_type="news",
            url="https://example.test/at-1",
            collected_at=datetime(2026, 8, 1, 12, tzinfo=timezone.utc),
            market="at",
        )
        self.assertEqual(item.market, "at")

    def test_normalize_strips_quote_suffix(self) -> None:
        for form in ("VOE.VI", "VOE.vi", "VOE VI", "VOE-VI", "VOE.VI.VI"):
            self.assertEqual(normalize_at_ticker(form), "VOE", form)

    def test_normalize_keeps_bare_suffix_word(self) -> None:
        self.assertEqual(normalize_at_ticker("VI"), "VI")

    def test_normalize_keeps_isin(self) -> None:
        self.assertEqual(normalize_at_ticker("AT0000743059"), "AT0000743059")

    def test_import_at_suffix_routes_to_market(self) -> None:
        parsed = parse_company_inputs("VOE@AT", "us")
        self.assertEqual(parsed[0].ticker, "VOE")
        self.assertEqual(parsed[0].market, "at")
        parsed_dot = parse_company_inputs("VOE.VI", "us")
        self.assertEqual(parsed_dot[0].market, "at")


if __name__ == "__main__":
    unittest.main()
