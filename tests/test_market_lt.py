'''LT market foundation tests.'''
from datetime import date, datetime, timezone
import unittest

from investment_monitor import (
    ALLOWED_MARKETS,
    CollectionRequest,
    InformationItem,
)
from investment_monitor.company_import import parse_company_inputs
from investment_monitor.web_repository import (
    normalize_lt_ticker as normalize_ticker,
)

MARKET = "lt"


class MarketLtTests(unittest.TestCase):
    def test_market_is_declared(self) -> None:
        self.assertIn(MARKET, ALLOWED_MARKETS)

    def test_collection_request_accepts_market(self) -> None:
        request = CollectionRequest(
            tickers=("TEL1L",),
            start_date=date(2026, 8, 1),
            end_date=date(2026, 8, 2),
            markets={"TEL1L": MARKET},
        )
        self.assertEqual(request.market_for("TEL1L"), MARKET)

    def test_information_item_accepts_market(self) -> None:
        item = InformationItem(
            source="news",
            source_type="news",
            external_id="lt-1",
            tickers=("TEL1L",),
            issuer="TEL1L",
            published_at=datetime(2026, 8, 1, tzinfo=timezone.utc),
            title="Baltic headline",
            document_type="news",
            url="https://example.test/lt-1",
            collected_at=datetime(2026, 8, 1, 12, tzinfo=timezone.utc),
            market=MARKET,
        )
        self.assertEqual(item.market, MARKET)

    def test_normalize_strips_quote_suffix(self) -> None:
        for form in (
            "TEL1L.VL",
            "TEL1L.vl",
            "TEL1L VL",
            "TEL1L-VL",
            "TEL1L.VL.VL",
        ):
            self.assertEqual(normalize_ticker(form), "TEL1L", form)

    def test_normalize_keeps_bare_suffix_word(self) -> None:
        self.assertEqual(normalize_ticker("VL"), "VL")

    def test_normalize_keeps_isin(self) -> None:
        self.assertEqual(normalize_ticker("LT0000128092"), "LT0000128092")

    def test_import_at_suffix_routes_to_market(self) -> None:
        parsed = parse_company_inputs("TEL1L@LT", "us")
        self.assertEqual(parsed[0].ticker, "TEL1L")
        self.assertEqual(parsed[0].market, MARKET)
        parsed_dot = parse_company_inputs("TEL1L.VL", "us")
        self.assertEqual(parsed_dot[0].market, MARKET)


if __name__ == "__main__":
    unittest.main()
