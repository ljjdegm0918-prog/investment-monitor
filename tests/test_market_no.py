'''NO market foundation tests.'''
from datetime import date, datetime, timezone
import unittest

from investment_monitor import (
    ALLOWED_MARKETS,
    CollectionRequest,
    InformationItem,
)
from investment_monitor.company_import import parse_company_inputs
from investment_monitor.web_repository import (
    normalize_no_ticker as normalize_ticker,
)

MARKET = "no"


class MarketNoTests(unittest.TestCase):
    def test_market_is_declared(self) -> None:
        self.assertIn(MARKET, ALLOWED_MARKETS)

    def test_collection_request_accepts_market(self) -> None:
        request = CollectionRequest(
            tickers=("EQNR",),
            start_date=date(2026, 8, 1),
            end_date=date(2026, 8, 2),
            markets={"EQNR": MARKET},
        )
        self.assertEqual(request.market_for("EQNR"), MARKET)

    def test_information_item_accepts_market(self) -> None:
        item = InformationItem(
            source="news",
            source_type="news",
            external_id="no-1",
            tickers=("EQNR",),
            issuer="EQNR",
            published_at=datetime(2026, 8, 1, tzinfo=timezone.utc),
            title="Euronext headline",
            document_type="news",
            url="https://example.test/no-1",
            collected_at=datetime(2026, 8, 1, 12, tzinfo=timezone.utc),
            market=MARKET,
        )
        self.assertEqual(item.market, MARKET)

    def test_normalize_strips_quote_suffix(self) -> None:
        for form in (
            "EQNR.OL",
            "EQNR.ol",
            "EQNR OL",
            "EQNR-OL",
            "EQNR.OL.OL",
        ):
            self.assertEqual(normalize_ticker(form), "EQNR", form)

    def test_normalize_keeps_bare_suffix_word(self) -> None:
        self.assertEqual(normalize_ticker("OL"), "OL")

    def test_normalize_keeps_isin(self) -> None:
        self.assertEqual(normalize_ticker("NO0010096985"), "NO0010096985")

    def test_import_at_suffix_routes_to_market(self) -> None:
        parsed = parse_company_inputs("EQNR@NO", "us")
        self.assertEqual(parsed[0].ticker, "EQNR")
        self.assertEqual(parsed[0].market, MARKET)
        parsed_dot = parse_company_inputs("EQNR.OL", "us")
        self.assertEqual(parsed_dot[0].market, MARKET)


if __name__ == "__main__":
    unittest.main()
