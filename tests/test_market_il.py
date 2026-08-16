"""IL market foundation tests."""

from datetime import date, datetime, timezone
import unittest

from investment_monitor import (
    ALLOWED_MARKETS,
    CollectionRequest,
    InformationItem,
    MARKET_IL,
)
from investment_monitor.company_import import parse_company_inputs
from investment_monitor.web_repository import normalize_il_ticker


class MarketIlTests(unittest.TestCase):
    def test_market_is_declared(self) -> None:
        self.assertEqual(MARKET_IL, "il")
        self.assertIn("il", ALLOWED_MARKETS)

    def test_collection_request_accepts_market(self) -> None:
        request = CollectionRequest(
            tickers=("TEVA",),
            start_date=date(2026, 8, 1),
            end_date=date(2026, 8, 2),
            markets={"TEVA": "il"},
        )
        self.assertEqual(request.market_for("TEVA"), "il")

    def test_information_item_accepts_market(self) -> None:
        item = InformationItem(
            source="news",
            source_type="news",
            external_id="il-1",
            tickers=("TEVA",),
            issuer="Teva",
            published_at=datetime(2026, 8, 1, tzinfo=timezone.utc),
            title="Israel headline",
            document_type="news",
            url="https://example.test/il-1",
            collected_at=datetime(2026, 8, 1, 12, tzinfo=timezone.utc),
            market="il",
        )
        self.assertEqual(item.market, "il")

    def test_normalize_strips_quote_suffix(self) -> None:
        for form in ("TEVA.TA", "TEVA.ta", "TEVA TA", "TEVA-TA", "TEVA.TA.TA"):
            self.assertEqual(normalize_il_ticker(form), "TEVA", form)

    def test_normalize_keeps_bare_suffix_word(self) -> None:
        self.assertEqual(normalize_il_ticker("TA"), "TA")

    def test_normalize_keeps_isin(self) -> None:
        self.assertEqual(normalize_il_ticker("IL0006290121"), "IL0006290121")

    def test_import_at_suffix_routes_to_market(self) -> None:
        parsed = parse_company_inputs("TEVA@IL", "us")
        self.assertEqual(parsed[0].ticker, "TEVA")
        self.assertEqual(parsed[0].market, "il")
        parsed_dot = parse_company_inputs("TEVA.TA", "us")
        self.assertEqual(parsed_dot[0].market, "il")


if __name__ == "__main__":
    unittest.main()
