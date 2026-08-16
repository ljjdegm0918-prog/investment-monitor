'''PT market foundation tests.'''
from datetime import date, datetime, timezone
import unittest

from investment_monitor import (
    ALLOWED_MARKETS,
    CollectionRequest,
    InformationItem,
)
from investment_monitor.company_import import parse_company_inputs
from investment_monitor.web_repository import (
    normalize_pt_ticker as normalize_ticker,
)

MARKET = "pt"


class MarketPtTests(unittest.TestCase):
    def test_market_is_declared(self) -> None:
        self.assertIn(MARKET, ALLOWED_MARKETS)

    def test_collection_request_accepts_market(self) -> None:
        request = CollectionRequest(
            tickers=("EDP",),
            start_date=date(2026, 8, 1),
            end_date=date(2026, 8, 2),
            markets={"EDP": MARKET},
        )
        self.assertEqual(request.market_for("EDP"), MARKET)

    def test_information_item_accepts_market(self) -> None:
        item = InformationItem(
            source="news",
            source_type="news",
            external_id="pt-1",
            tickers=("EDP",),
            issuer="EDP",
            published_at=datetime(2026, 8, 1, tzinfo=timezone.utc),
            title="Euronext headline",
            document_type="news",
            url="https://example.test/pt-1",
            collected_at=datetime(2026, 8, 1, 12, tzinfo=timezone.utc),
            market=MARKET,
        )
        self.assertEqual(item.market, MARKET)

    def test_normalize_strips_quote_suffix(self) -> None:
        for form in (
            "EDP.LS",
            "EDP.ls",
            "EDP LS",
            "EDP-LS",
            "EDP.LS.LS",
        ):
            self.assertEqual(normalize_ticker(form), "EDP", form)

    def test_normalize_keeps_bare_suffix_word(self) -> None:
        self.assertEqual(normalize_ticker("LS"), "LS")

    def test_normalize_keeps_isin(self) -> None:
        self.assertEqual(normalize_ticker("PTEDP0AM0009"), "PTEDP0AM0009")

    def test_import_at_suffix_routes_to_market(self) -> None:
        parsed = parse_company_inputs("EDP@PT", "us")
        self.assertEqual(parsed[0].ticker, "EDP")
        self.assertEqual(parsed[0].market, MARKET)
        parsed_dot = parse_company_inputs("EDP.LS", "us")
        self.assertEqual(parsed_dot[0].market, MARKET)


if __name__ == "__main__":
    unittest.main()
