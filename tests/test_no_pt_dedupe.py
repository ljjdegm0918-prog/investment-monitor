"""NO/PT soft-dedupe tests (annotate-only)."""

import unittest

from investment_monitor.dedupe import annotate_feed_items, dedupe_key


def news_item(source, market, title, day="2026-08-14T09:00:00+00:00"):
    return {
        "source": source,
        "source_type": "news",
        "market": market,
        "ticker": "X",
        "title": title,
        "published_at": day,
        "external_id": f"{source}-1",
    }


class NoPtDedupeTests(unittest.TestCase):
    def test_news_pairs_cross_source_per_market(self):
        for market, yahoo, google in (
            ("no", "yahoo_no", "google_news_no"),
            ("pt", "yahoo_pt", "google_news_pt"),
        ):
            with self.subTest(market=market):
                annotated = annotate_feed_items([
                    news_item(yahoo, market, "Quarterly report"),
                    news_item(google, market, "Quarterly report"),
                ])
                self.assertEqual(len(annotated), 2)
                self.assertEqual(annotated[0]["also_seen_on"], [google])

    def test_no_disclosure_rows_are_never_cross_annotated(self):
        item = {
            "source": "newsweb_no",
            "source_type": "regulatory_filing",
            "market": "no",
            "ticker": "EQNR",
            "title": "x",
            "published_at": "2026-08-14T09:00:00+00:00",
            "external_id": "no:1",
        }
        self.assertIsNone(dedupe_key(item))
        annotated = annotate_feed_items([item])
        self.assertEqual(annotated[0].get("also_seen_on"), None)


if __name__ == "__main__":
    unittest.main()
