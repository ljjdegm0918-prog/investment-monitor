"""India market/disclosure/universe/news/dedupe tests."""

from datetime import date, datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from investment_monitor import (
    ALLOWED_MARKETS,
    CollectionRequest,
    InformationItem,
    MARKET_IN,
)
from investment_monitor.company_import import parse_company_inputs
from investment_monitor.dedupe import annotate_feed_items, dedupe_key
from investment_monitor.registry import SOURCE_MARKETS, create_default_registry
from investment_monitor.sources.in_news import (
    GoogleInNewsConnector,
    YahooInNewsConnector,
)
from investment_monitor.sources.in_news.symbols import in_yahoo_symbol
from investment_monitor.sources.nse_announcements import (
    NseAnnouncementsConnector,
)
from investment_monitor.universe.in_universe import (
    in_universe_name_map,
    refresh_in_universe,
)
from investment_monitor.web_repository import normalize_in_ticker

CSV = (
    "SYMBOL,NAME OF COMPANY, SERIES, DATE OF LISTING, PAID UP VALUE, MARKET LOT, ISIN NUMBER, FACE VALUE\n"
    "RELIANCE,Reliance Industries Limited,EQ,01-JAN-1995,10,1,INE002A01018,10\n"
    "TCS,Tata Consultancy Services Limited,EQ,25-AUG-2004,1,1,INE467B01029,1\n"
    "XYZ,XYZ Mutual Fund,BE,01-JAN-2020,10,1,INE999X01010,10\n"
)


class FakeResponse:
    def __init__(self, payload):
        self._payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return None

    def read(self):
        return self._payload


class FakeNseClient:
    def __init__(self, records):
        self.records = records
        self.calls = []

    def fetch_day(self, day):
        self.calls.append(day)
        return self.records


def record(seq_id, symbol, desc, an_dt):
    return {
        "seq_id": seq_id, "symbol": symbol, "sm_name": f"{symbol} Ltd",
        "sm_isin": "INE002A01018", "desc": desc, "an_dt": an_dt,
        "attchmntText": "summary", "attchmntFile": f"https://nse.test/{seq_id}.pdf",
        "smIndustry": "Energy",
    }


class IndiaTests(unittest.TestCase):
    def test_market_basics(self):
        self.assertEqual(MARKET_IN, "in")
        self.assertIn("in", ALLOWED_MARKETS)
        self.assertEqual(normalize_in_ticker("RELIANCE.NS"), "RELIANCE")
        self.assertEqual(normalize_in_ticker("TCS.BO"), "TCS")
        self.assertEqual(normalize_in_ticker("BO"), "BO")
        self.assertEqual(normalize_in_ticker("INE002A01018"), "INE002A01018")
        parsed = parse_company_inputs("RELIANCE@IN", "us")
        self.assertEqual(parsed[0].market, "in")
        parsed_ns = parse_company_inputs("RELIANCE.NS", "us")
        self.assertEqual(parsed_ns[0].market, "in")

    def test_nse_connector_filters_and_dates(self):
        day = date(2026, 8, 14)
        client = FakeNseClient([
            record("106746008", "RELIANCE", "Outcome of Board Meeting", "14-Aug-2026 23:59:17"),
            record("106746009", "TCS", "Press Release", "14-Aug-2026 10:00:00"),
            record("106746010", "WIPRO", "Outcome of Board Meeting", "14-Aug-2026 09:00:00"),
        ])
        connector = NseAnnouncementsConnector(client=client)
        request = CollectionRequest(
            tickers=("RELIANCE",),
            start_date=day, end_date=day, markets={"RELIANCE": "in"},
        )
        items = connector.collect(request)
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0].external_id, "nse:106746008")
        self.assertEqual(items[0].tickers, ("RELIANCE",))
        self.assertEqual(client.calls, [day])
        # 非 in 市场零 HTTP
        client2 = FakeNseClient([])
        connector2 = NseAnnouncementsConnector(client=client2)
        foreign = CollectionRequest(
            tickers=("AAPL",), start_date=day, end_date=day, markets={"AAPL": "us"},
        )
        self.assertEqual(connector2.collect(foreign), [])
        self.assertEqual(client2.calls, [])

    def test_universe_keeps_only_eq_series(self):
        temporary = TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        payload = refresh_in_universe(
            path=root / "in.json",
            opener=lambda request, timeout: FakeResponse(CSV.encode("utf-8")),
        )
        self.assertEqual([i["ticker"] for i in payload["items"]], ["RELIANCE", "TCS"])
        name_map = in_universe_name_map(root / "in.json")
        self.assertEqual(name_map["RELIANCE"]["isin"], "INE002A01018")

    def test_news_and_registry(self):
        self.assertEqual(in_yahoo_symbol("RELIANCE"), "RELIANCE.NS")
        self.assertEqual(SOURCE_MARKETS["nse_announcements"], "in")
        self.assertEqual(SOURCE_MARKETS["yahoo_in"], "in")
        registry = create_default_registry()
        for name in ("nse_announcements", "yahoo_in", "google_news_in"):
            self.assertIn(name, registry.registered_names)

    def test_dedupe_annotates_nse_and_news(self):
        annotated = annotate_feed_items([
            {
                "source": "yahoo_in", "source_type": "news", "market": "in",
                "ticker": "RELIANCE", "title": "Results", "external_id": "y1",
                "published_at": "2026-08-14T14:00:00+00:00",
            },
            {
                "source": "google_news_in", "source_type": "news", "market": "in",
                "ticker": "RELIANCE", "title": "Results", "external_id": "g1",
                "published_at": "2026-08-14T14:00:00+00:00",
            },
        ])
        self.assertEqual(annotated[0]["also_seen_on"], ["google_news_in"])
        filing_key = dedupe_key({
            "source": "nse_announcements", "source_type": "regulatory_filing",
            "market": "in", "ticker": "RELIANCE", "title": "x",
            "external_id": "nse:106746008",
            "published_at": "2026-08-14T18:29:17+00:00",
        })
        self.assertEqual(filing_key, "in:filing:nse:nse:106746008")


if __name__ == "__main__":
    unittest.main()
