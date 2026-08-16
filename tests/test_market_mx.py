"""MX market foundation tests."""

from datetime import date, datetime, timezone
import unittest

from investment_monitor import (
    ALLOWED_MARKETS,
    CollectionRequest,
    InformationItem,
    MARKET_MX,
)
from investment_monitor.company_import import parse_company_inputs
from investment_monitor.web_repository import normalize_mx_ticker


class MarketMxTests(unittest.TestCase):
    def test_market_is_declared(self) -> None:
        self.assertEqual(MARKET_MX, "mx")
        self.assertIn("mx", ALLOWED_MARKETS)

    def test_collection_request_accepts_market(self) -> None:
        request = CollectionRequest(
            tickers=("WALMEX",),
            start_date=date(2026, 8, 1),
            end_date=date(2026, 8, 2),
            markets={"WALMEX": "mx"},
        )
        self.assertEqual(request.market_for("WALMEX"), "mx")

    def test_information_item_accepts_market(self) -> None:
        item = InformationItem(
            source="news",
            source_type="news",
            external_id="mx-1",
            tickers=("WALMEX",),
            issuer="WALMEX",
            published_at=datetime(2026, 8, 1, tzinfo=timezone.utc),
            title="Mexico headline",
            document_type="news",
            url="https://example.test/mx-1",
            collected_at=datetime(2026, 8, 1, 12, tzinfo=timezone.utc),
            market="mx",
        )
        self.assertEqual(item.market, "mx")

    def test_normalize_strips_quote_suffix(self) -> None:
        for form in ("WALMEX.MX", "WALMEX.mx", "WALMEX MX", "WALMEX-MX", "WALMEX.MX.MX"):
            self.assertEqual(normalize_mx_ticker(form), "WALMEX", form)

    def test_normalize_keeps_bare_suffix_word(self) -> None:
        self.assertEqual(normalize_mx_ticker("MX"), "MX")

    def test_normalize_keeps_isin(self) -> None:
        self.assertEqual(normalize_mx_ticker("MX01WA000038"), "MX01WA000038")

    def test_import_at_suffix_routes_to_market(self) -> None:
        parsed = parse_company_inputs("WALMEX@MX", "us")
        self.assertEqual(parsed[0].ticker, "WALMEX")
        self.assertEqual(parsed[0].market, "mx")
        parsed_dot = parse_company_inputs("WALMEX.MX", "us")
        self.assertEqual(parsed_dot[0].market, "mx")


if __name__ == "__main__":
    unittest.main()
