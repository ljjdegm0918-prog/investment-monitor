"""Nasdaq Baltic issuer announcement connector tests."""

from datetime import date, datetime, timezone
import unittest

from investment_monitor.models import CollectionRequest
from investment_monitor.sources.nasdaq_baltic_news.client import (
    RELEASE_MARKETS,
)
from investment_monitor.sources.nasdaq_baltic_news.connector import (
    NasdaqBalticNewsConnector,
    _parse_published,
)
from investment_monitor.sources.nasdaq_baltic_news.matcher import (
    BalticCompanyMatcher,
    normalize_company_name,
)


class FakeClient:
    def __init__(self, records_by_day):
        self.records_by_day = records_by_day
        self.calls = []

    def fetch_market_day(self, day, market):
        self.calls.append((day, market))
        return self.records_by_day.get(day, [])


class FakeMatcher:
    def __init__(self, mapping):
        self.mapping = mapping
        self.loaded = []

    def load_universe(self, market):
        self.loaded.append(market)

    def match(self, company, tickers):
        return self.mapping.get(company)


def record(disclosure_id, company, headline, published, market):
    return {
        "disclosureId": disclosure_id,
        "company": company,
        "headline": headline,
        "published": published,
        "market": market,
        "cnsCategory": "Company Announcement",
        "messageUrl": f"https://view.news.eu.nasdaq.com/view?id={disclosure_id}",
        "language": "en",
        "cnsTypeId": "1",
    }


class NasdaqBalticNewsTests(unittest.TestCase):
    def test_non_baltic_market_makes_zero_http_calls(self):
        client = FakeClient({})
        connector = NasdaqBalticNewsConnector(client=client, matcher=FakeMatcher({}))
        request = CollectionRequest(
            tickers=("AAPL",),
            start_date=date(2026, 8, 10),
            end_date=date(2026, 8, 10),
            markets={"AAPL": "us"},
        )
        items = connector.collect(request)
        self.assertEqual(items, [])
        self.assertEqual(client.calls, [])
        self.assertEqual(connector.last_errors, ())

    def test_collects_issuer_announcements_for_ee(self):
        day = date(2026, 8, 10)
        client = FakeClient({
            day: [
                record(1, "Tallinna Kaubamaja Grupp", "Interim report", "2026-08-10 08:00:00 +0300", "Main Market, Tallinn"),
                record(2, "Nasdaq Tallinn", "Exchange notice", "2026-08-10 09:00:00 +0300", "NASDAQ OMX, Tallinn"),
                record(3, "Unknown Issuer AS", "Unmatched", "2026-08-10 10:00:00 +0300", "First North Estonia"),
            ]
        })
        connector = NasdaqBalticNewsConnector(
            client=client,
            matcher=FakeMatcher({"Tallinna Kaubamaja Grupp": "TKM1T"}),
        )
        request = CollectionRequest(
            tickers=("TKM1T",),
            start_date=day,
            end_date=day,
            markets={"TKM1T": "ee"},
        )
        items = connector.collect(request)
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0].tickers, ("TKM1T",))
        self.assertEqual(items[0].external_id, "baltic:1")
        self.assertEqual(items[0].market, "ee")
        self.assertEqual(client.calls, [(day, "ee")])

    def test_date_window_requests_each_day_once_per_market(self):
        start = date(2026, 8, 10)
        end = date(2026, 8, 12)
        client = FakeClient({})
        connector = NasdaqBalticNewsConnector(client=client, matcher=FakeMatcher({}))
        connector.collect(CollectionRequest(
            tickers=("TAL1T", "SAF1R"),
            start_date=start,
            end_date=end,
            markets={"TAL1T": "ee", "SAF1R": "lv"},
        ))
        expected = [
            (start, "ee"), (date(2026, 8, 11), "ee"), (end, "ee"),
            (start, "lv"), (date(2026, 8, 11), "lv"), (end, "lv"),
        ]
        self.assertEqual(client.calls, expected)

    def test_parse_published_accepts_official_format(self):
        parsed = _parse_published("2026-08-14 14:00:00 +0300")
        self.assertEqual(parsed, datetime(2026, 8, 14, 11, 0, tzinfo=timezone.utc))

    def test_matcher_normalization_is_conservative(self):
        self.assertEqual(normalize_company_name("  EfTEN Real Estate Fund , "), "EFTEN REAL ESTATE FUND")
        self.assertEqual(normalize_company_name("AS  LHV Group."), "AS LHV GROUP")

    def test_release_market_table_covers_three_markets(self):
        self.assertEqual(set(RELEASE_MARKETS), {"ee", "lv", "lt"})


if __name__ == "__main__":
    unittest.main()
