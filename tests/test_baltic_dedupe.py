"""Baltic soft-dedupe tests (annotate-only, never drops rows)."""

import unittest

from investment_monitor.dedupe import annotate_feed_items, dedupe_key


def news_item(source, market, title, day="2026-08-14T09:00:00+00:00", ticker="TAL1T"):
    return {
        "source": source,
        "source_type": "news",
        "market": market,
        "ticker": ticker,
        "title": title,
        "published_at": day,
        "external_id": f"{source}-1",
    }


def filing_item(market, external_id, ticker="TAL1T"):
    return {
        "source": "nasdaq_baltic_news",
        "source_type": "regulatory_filing",
        "market": market,
        "ticker": ticker,
        "title": "Quarterly report",
        "published_at": "2026-08-14T08:00:00+00:00",
        "external_id": external_id,
    }


class BalticDedupeTests(unittest.TestCase):
    def test_baltic_news_pairs_cross_source_on_tallinn_day_and_title(self):
        for market, yahoo, google in (
            ("ee", "yahoo_ee", "google_news_ee"),
            ("lv", "yahoo_lv", "google_news_lv"),
            ("lt", "yahoo_lt", "google_news_lt"),
        ):
            with self.subTest(market=market):
                items = [
                    news_item(yahoo, market, "Earnings update"),
                    news_item(google, market, "Earnings update"),
                ]
                annotated = annotate_feed_items(items)
                self.assertEqual(len(annotated), 2)
                self.assertEqual(
                    annotated[0]["also_seen_on"], [google]
                )
                self.assertEqual(
                    annotated[1]["also_seen_on"], [yahoo]
                )

    def test_baltic_filing_uses_stable_disclosure_id(self):
        key = dedupe_key(filing_item("ee", "baltic:1458423"))
        self.assertEqual(key, "ee:filing:baltic:baltic:1458423")
        # 同披露 id 的不同行会被 annotate，但绝不丢行
        rows = [
            filing_item("ee", "baltic:1458423"),
            filing_item("ee", "baltic:1458423"),
        ]
        annotated = annotate_feed_items(rows)
        self.assertEqual(len(annotated), 2)
        self.assertEqual(annotated[0]["dedupe_count"], 2)

    def test_baltic_filing_title_fallback_is_source_scoped(self):
        item = filing_item("lv", "")
        item["external_id"] = ""
        key = dedupe_key(item)
        self.assertIn("lv:filing:title:nasdaq_baltic_news:", key or "")

    def test_foreign_rows_are_not_annotated(self):
        annotated = annotate_feed_items([
            news_item("yahoo_us", "us", "Baltic style title"),
        ])
        self.assertEqual(annotated[0].get("also_seen_on"), None)


if __name__ == "__main__":
    unittest.main()
