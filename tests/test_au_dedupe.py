from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from investment_monitor import (
    InformationItem,
    SQLiteInformationRepository,
    WebRepository,
)
from investment_monitor.config import SourceConfig
from investment_monitor.dedupe import annotate_feed_items, dedupe_key
from investment_monitor.web_repository import FeedFilters


def feed_item(
    source: str,
    external_id: str,
    *,
    title: str = "BHP quarterly output rises",
    ticker: str = "BHP",
    market: str = "au",
    source_type: str = "news",
    published: datetime = None,
    raw_metadata: dict = None,
) -> dict:
    published = published or datetime(
        2026, 8, 5, 10, 0, tzinfo=timezone.utc
    )
    return {
        "source": source,
        "source_type": source_type,
        "external_id": external_id,
        "ticker": ticker,
        "market": market,
        "title": title,
        "published_at": published.isoformat(),
        "effective_at": published.isoformat(),
        "raw_metadata": raw_metadata or {},
    }


class AuDedupeKeyTests(unittest.TestCase):
    def test_au_market_key_is_non_empty_for_news(self) -> None:
        item = feed_item("yahoo_au", "y-1")

        self.assertIsNotNone(dedupe_key(item))

    def test_au_news_folds_across_sources_by_ticker_day_title(self) -> None:
        first = feed_item("yahoo_au", "y-1")
        second = feed_item("google_news_au", "g-1")

        self.assertEqual(dedupe_key(first), dedupe_key(second))
        self.assertTrue(dedupe_key(first).startswith("au-news:"))
        self.assertIn("BHP|2026-08-05|", dedupe_key(first))

    def test_au_news_different_day_does_not_fold(self) -> None:
        first = feed_item(
            "yahoo_au",
            "y-1",
            published=datetime(2026, 8, 5, 10, 0, tzinfo=timezone.utc),
        )
        second = feed_item(
            "google_news_au",
            "g-1",
            published=datetime(2026, 8, 6, 10, 0, tzinfo=timezone.utc),
        )

        self.assertNotEqual(dedupe_key(first), dedupe_key(second))

    def test_au_news_different_title_does_not_fold(self) -> None:
        first = feed_item("yahoo_au", "y-1", title="BHP quarterly output rises")
        second = feed_item(
            "google_news_au",
            "g-1",
            title="ASX miners rally on iron ore",
        )

        self.assertNotEqual(dedupe_key(first), dedupe_key(second))

    def test_au_news_different_ticker_does_not_fold(self) -> None:
        first = feed_item("yahoo_au", "y-1", ticker="BHP")
        second = feed_item("google_news_au", "g-1", ticker="CBA")

        self.assertNotEqual(dedupe_key(first), dedupe_key(second))

    def test_sydney_day_uses_australia_timezone(self) -> None:
        late_utc = feed_item(
            "yahoo_au",
            "y-1",
            published=datetime(2026, 8, 5, 23, 30, tzinfo=timezone.utc),
        )
        early_utc = feed_item(
            "google_news_au",
            "g-1",
            published=datetime(2026, 8, 5, 13, 0, tzinfo=timezone.utc),
        )

        self.assertIn("2026-08-06", dedupe_key(late_utc))
        self.assertIn("2026-08-05", dedupe_key(early_utc))

    def test_au_filing_same_document_key_pairs(self) -> None:
        first = feed_item(
            "asx_announcements",
            "2924-03111504-3A697237",
            source_type="regulatory_filing",
            raw_metadata={"document_key": "2924-03111504-3A697237"},
        )
        second = feed_item(
            "asx_announcements",
            "2924-03111504-3A697237",
            source_type="regulatory_filing",
            raw_metadata={"document_key": "2924-03111504-3A697237"},
        )

        self.assertEqual(dedupe_key(first), dedupe_key(second))
        self.assertTrue(dedupe_key(first).startswith("au:filing:asx:"))

    def test_au_filing_title_fallback_is_source_scoped(self) -> None:
        title = "Quarterly Activities Report"
        first = feed_item(
            "asx_announcements",
            "",
            source_type="regulatory_filing",
            title=title,
        )
        second = feed_item(
            "hypothetical_other_source",
            "",
            source_type="regulatory_filing",
            title=title,
        )

        self.assertTrue(
            dedupe_key(first).startswith("au:filing:title:asx_announcements:")
        )
        self.assertNotEqual(dedupe_key(first), dedupe_key(second))

    def test_au_filing_different_day_does_not_fold(self) -> None:
        first = feed_item(
            "asx_announcements",
            "",
            source_type="regulatory_filing",
            published=datetime(2026, 8, 5, 10, 0, tzinfo=timezone.utc),
        )
        second = feed_item(
            "asx_announcements",
            "",
            source_type="regulatory_filing",
            published=datetime(2026, 8, 6, 10, 0, tzinfo=timezone.utc),
        )

        self.assertNotEqual(dedupe_key(first), dedupe_key(second))

    def test_us_market_still_has_no_key(self) -> None:
        item = feed_item("sec", "sec-1", market="us")

        self.assertIsNone(dedupe_key(item))


class AuAnnotateTests(unittest.TestCase):
    def test_news_same_key_keeps_both_rows_annotated(self) -> None:
        first = feed_item("yahoo_au", "y-1")
        second = feed_item("google_news_au", "g-1")

        annotated = annotate_feed_items([first, second])

        self.assertEqual(len(annotated), 2)
        self.assertEqual(annotated[0]["also_seen_on"], ["google_news_au"])
        self.assertEqual(
            annotated[0]["also_seen_on_labels"],
            ["Google News (AU)"],
        )
        self.assertEqual(annotated[1]["also_seen_on"], ["yahoo_au"])
        self.assertEqual(
            annotated[1]["also_seen_on_labels"],
            ["Yahoo Finance AU"],
        )
        self.assertEqual(annotated[0]["dedupe_count"], 2)

    def test_switch_off_returns_all_rows_without_annotations(self) -> None:
        first = feed_item("yahoo_au", "y-1")
        second = feed_item("google_news_au", "g-1")

        annotated = annotate_feed_items([first, second], enabled=False)

        self.assertEqual(len(annotated), 2)
        self.assertNotIn("also_seen_on", annotated[0])
        self.assertNotIn("also_seen_on", annotated[1])

    def test_cross_source_news_different_title_is_not_annotated(self) -> None:
        first = feed_item("yahoo_au", "y-1", title="BHP quarterly output rises")
        second = feed_item(
            "google_news_au",
            "g-1",
            title="ASX miners rally on iron ore",
        )

        annotated = annotate_feed_items([first, second])

        self.assertEqual(len(annotated), 2)
        self.assertNotIn("also_seen_on", annotated[0])
        self.assertNotIn("also_seen_on", annotated[1])


class WebRepositoryAuDedupeTests(unittest.TestCase):
    def test_display_annotates_au_news_while_raw_keeps_rows(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            database_path = Path(temporary_directory) / "web.sqlite3"
            items = SQLiteInformationRepository(database_path)
            repository = WebRepository(
                database_path,
                allowed_sources=("yahoo_au", "google_news_au"),
                known_sources=(
                    SourceConfig(
                        "yahoo_au",
                        "Yahoo Finance AU",
                        "news",
                        True,
                    ),
                    SourceConfig(
                        "google_news_au",
                        "Google News (AU)",
                        "news",
                        True,
                    ),
                ),
                implemented_sources=("yahoo_au", "google_news_au"),
            )
            repository.add_companies_batch(
                "BHP",
                ("holdings",),
                None,
                market="au",
            )
            published = datetime(2026, 8, 5, 10, 0, tzinfo=timezone.utc)
            items.save([
                InformationItem(
                    source="yahoo_au",
                    source_type="news",
                    external_id="y-1",
                    tickers=("BHP",),
                    issuer="BHP",
                    published_at=published,
                    title="BHP quarterly output rises",
                    document_type="news",
                    url="https://example.com/y",
                    collected_at=published,
                    raw_metadata={},
                    market="au",
                    effective_at=published,
                ),
                InformationItem(
                    source="google_news_au",
                    source_type="news",
                    external_id="g-1",
                    tickers=("BHP",),
                    issuer="BHP",
                    published_at=published,
                    title="BHP quarterly output rises",
                    document_type="news",
                    url="https://example.com/g",
                    collected_at=published,
                    raw_metadata={},
                    market="au",
                    effective_at=published,
                ),
            ])

            raw = repository.query_feed(FeedFilters())
            display = repository.query_feed_display(FeedFilters())

            self.assertEqual(raw.total, 2)
            self.assertEqual(len(display.items), 2)
            labels = {
                tuple(item["also_seen_on_labels"])
                for item in display.items
                if "also_seen_on_labels" in item
            }
            self.assertEqual(
                labels,
                {("Google News (AU)",), ("Yahoo Finance AU",)},
            )


if __name__ == "__main__":
    unittest.main()
