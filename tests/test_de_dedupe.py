from datetime import datetime, timezone
import unittest

from investment_monitor.dedupe import annotate_feed_items, dedupe_key


def feed_item(
    source: str,
    external_id: str,
    *,
    title: str = "SAP headline",
    ticker: str = "SAP",
    market: str = "de",
    source_type: str = "news",
    published: datetime = None,
) -> dict:
    published = published or datetime(2026, 8, 7, 12, 0, tzinfo=timezone.utc)
    return {
        "source": source,
        "source_type": source_type,
        "external_id": external_id,
        "ticker": ticker,
        "market": market,
        "title": title,
        "published_at": published.isoformat(),
        "effective_at": published.isoformat(),
        "raw_metadata": {},
    }


class DeDedupeTests(unittest.TestCase):
    def test_eqs_filings_pair_on_document_id(self) -> None:
        a = feed_item(
            "eqs_dgap",
            "abc-123",
            source_type="regulatory_filing",
            title="One",
        )
        b = feed_item(
            "eqs_dgap",
            "abc-123",
            source_type="regulatory_filing",
            title="Different title same id",
        )
        self.assertEqual(dedupe_key(a), dedupe_key(b))
        self.assertTrue(str(dedupe_key(a)).startswith("de:filing:eqs:"))

    def test_news_pairs_across_yahoo_and_google(self) -> None:
        a = feed_item("yahoo_de", "y1", title="SAP cloud revenue rises")
        b = feed_item("google_news_de", "g1", title="SAP cloud revenue rises")
        self.assertEqual(dedupe_key(a), dedupe_key(b))
        annotated = annotate_feed_items([a, b])
        self.assertEqual(len(annotated), 2)
        labels = annotated[0].get("also_seen_on_labels") or annotated[0].get(
            "also_from_labels"
        )
        self.assertTrue(labels)

    def test_non_de_unaffected_key_prefix(self) -> None:
        item = feed_item("yahoo_de", "x", market="us")
        self.assertIsNone(dedupe_key(item))


if __name__ == "__main__":
    unittest.main()
