'''EE market foundation tests.'''
from datetime import date, datetime, timezone
import unittest

from investment_monitor import (
    ALLOWED_MARKETS,
    CollectionRequest,
    InformationItem,
)
from investment_monitor.company_import import parse_company_inputs
from investment_monitor.web_repository import (
    normalize_ee_ticker as normalize_ticker,
)

MARKET = "ee"


class MarketEeTests(unittest.TestCase):
    def test_market_is_declared(self) -> None:
        self.assertIn(MARKET, ALLOWED_MARKETS)

    def test_collection_request_accepts_market(self) -> None:
        request = CollectionRequest(
            tickers=("TAL1T",),
            start_date=date(2026, 8, 1),
            end_date=date(2026, 8, 2),
            markets={"TAL1T": MARKET},
        )
        self.assertEqual(request.market_for("TAL1T"), MARKET)

    def test_information_item_accepts_market(self) -> None:
        item = InformationItem(
            source="news",
            source_type="news",
            external_id="ee-1",
            tickers=("TAL1T",),
            issuer="TAL1T",
            published_at=datetime(2026, 8, 1, tzinfo=timezone.utc),
            title="Baltic headline",
            document_type="news",
            url="https://example.test/ee-1",
            collected_at=datetime(2026, 8, 1, 12, tzinfo=timezone.utc),
            market=MARKET,
        )
        self.assertEqual(item.market, MARKET)

    def test_normalize_strips_quote_suffix(self) -> None:
        for form in (
            "TAL1T.TL",
            "TAL1T.tl",
            "TAL1T TL",
            "TAL1T-TL",
            "TAL1T.TL.TL",
        ):
            self.assertEqual(normalize_ticker(form), "TAL1T", form)

    def test_normalize_keeps_bare_suffix_word(self) -> None:
        self.assertEqual(normalize_ticker("TL"), "TL")

    def test_normalize_keeps_isin(self) -> None:
        self.assertEqual(normalize_ticker("EE3100004466"), "EE3100004466")

    def test_import_at_suffix_routes_to_market(self) -> None:
        parsed = parse_company_inputs("TAL1T@EE", "us")
        self.assertEqual(parsed[0].ticker, "TAL1T")
        self.assertEqual(parsed[0].market, MARKET)
        parsed_dot = parse_company_inputs("TAL1T.TL", "us")
        self.assertEqual(parsed_dot[0].market, MARKET)


if __name__ == "__main__":
    unittest.main()
