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
    title: str = "Adnams raises funds for new brewery",
    ticker: str = "ADB",
    market: str = "aq",
    source_type: str = "news",
    published: datetime = None,
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
        "raw_metadata": {},
    }


class AqDedupeKeyTests(unittest.TestCase):
    def test_aq_news_folds_across_sources_by_ticker_day_title(self) -> None:
        first = feed_item("yahoo_aq", "y-1")
        second = feed_item("google_news_aq", "g-1")

        self.assertEqual(dedupe_key(first), dedupe_key(second))
        self.assertTrue(dedupe_key(first).startswith("aq-news:"))
        self.assertIn("ADB|2026-08-05|", dedupe_key(first))

    def test_aq_news_different_day_does_not_fold(self) -> None:
        first = feed_item(
            "yahoo_aq",
            "y-1",
            published=datetime(2026, 8, 5, 10, 0, tzinfo=timezone.utc),
        )
        second = feed_item(
            "google_news_aq",
            "g-1",
            published=datetime(2026, 8, 6, 10, 0, tzinfo=timezone.utc),
        )

        self.assertNotEqual(dedupe_key(first), dedupe_key(second))

    def test_aq_news_different_title_does_not_fold(self) -> None:
        first = feed_item("yahoo_aq", "y-1", title="Adnams brewery raise")
        second = feed_item(
            "google_news_aq",
            "g-1",
            title="London small caps rally",
        )

        self.assertNotEqual(dedupe_key(first), dedupe_key(second))

    def test_aq_news_different_ticker_does_not_fold(self) -> None:
        first = feed_item("yahoo_aq", "y-1", ticker="ADB")
        second = feed_item("google_news_aq", "g-1", ticker="ALSP")

        self.assertNotEqual(dedupe_key(first), dedupe_key(second))

    def test_london_day_uses_british_timezone(self) -> None:
        # 23:30 UTC on 2026-08-09 is 00:30 BST on 2026-08-10: same London
        # day as 21:00 UTC on 2026-08-10, and a different day from
        # 23:30 UTC on 2026-08-10 (which is 00:30 BST on 2026-08-11).
        late_utc = feed_item(
            "yahoo_aq",
            "y-1",
            published=datetime(2026, 8, 9, 23, 30, tzinfo=timezone.utc),
        )
        evening_utc = feed_item(
            "google_news_aq",
            "g-1",
            published=datetime(2026, 8, 10, 21, 0, tzinfo=timezone.utc),
        )
        next_day_utc = feed_item(
            "google_news_aq",
            "g-2",
            published=datetime(2026, 8, 10, 23, 30, tzinfo=timezone.utc),
        )

        self.assertIn("2026-08-10", dedupe_key(late_utc))
        self.assertEqual(dedupe_key(late_utc), dedupe_key(evening_utc))
        self.assertIn("2026-08-11", dedupe_key(next_day_utc))
        self.assertNotEqual(dedupe_key(late_utc), dedupe_key(next_day_utc))

    def test_aq_filing_never_gets_a_key(self) -> None:
        item = feed_item(
            "aqse_announcements",
            "f-1",
            source_type="regulatory_filing",
        )

        self.assertIsNone(dedupe_key(item))

    def test_aq_market_key_is_non_empty_for_news(self) -> None:
        item = feed_item("yahoo_aq", "y-1")

        self.assertIsNotNone(dedupe_key(item))

    def test_non_aq_markets_still_use_their_own_rules(self) -> None:
        uk = feed_item(
            "yahoo_uk",
            "uk-1",
            market="uk",
            title="London headlines",
        )
        se = feed_item(
            "yahoo_se",
            "se-1",
            market="se",
            title="Stockholm headlines",
        )

        self.assertTrue(dedupe_key(uk).startswith("uk-news:"))
        self.assertTrue(dedupe_key(se).startswith("se-news:"))


class AqAnnotateFeedItemsTests(unittest.TestCase):
    def test_news_same_key_keeps_both_rows_annotated(self) -> None:
        first = feed_item("yahoo_aq", "y-1")
        second = feed_item("google_news_aq", "g-1")

        annotated = annotate_feed_items([first, second])

        self.assertEqual(len(annotated), 2)
        self.assertEqual(annotated[0]["also_seen_on"], ["google_news_aq"])
        self.assertEqual(
            annotated[0]["also_seen_on_labels"],
            ["Google News (AQ)"],
        )
        self.assertEqual(annotated[1]["also_seen_on"], ["yahoo_aq"])
        self.assertEqual(
            annotated[1]["also_seen_on_labels"],
            ["Yahoo Finance AQ"],
        )
        self.assertEqual(annotated[0]["dedupe_count"], 2)

    def test_switch_off_returns_all_rows_without_annotations(self) -> None:
        first = feed_item("yahoo_aq", "y-1")
        second = feed_item("google_news_aq", "g-1")

        annotated = annotate_feed_items([first, second], enabled=False)

        self.assertEqual(len(annotated), 2)
        self.assertNotIn("also_seen_on", annotated[0])
        self.assertNotIn("also_seen_on", annotated[1])


class WebRepositoryAqDedupeTests(unittest.TestCase):
    def test_display_annotates_aq_news_while_raw_keeps_rows(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            database_path = Path(temporary_directory) / "web.sqlite3"
            items = SQLiteInformationRepository(database_path)
            repository = WebRepository(
                database_path,
                allowed_sources=("yahoo_aq", "google_news_aq"),
                known_sources=(
                    SourceConfig(
                        "yahoo_aq",
                        "Yahoo Finance AQ",
                        "news",
                        True,
                    ),
                    SourceConfig(
                        "google_news_aq",
                        "Google News (AQ)",
                        "news",
                        True,
                    ),
                ),
                implemented_sources=("yahoo_aq", "google_news_aq"),
            )
            repository.add_companies_batch(
                "ADB",
                ("holdings",),
                None,
                market="aq",
            )
            published = datetime(2026, 8, 5, 10, 0, tzinfo=timezone.utc)
            items.save([
                InformationItem(
                    source="yahoo_aq",
                    source_type="news",
                    external_id="y-1",
                    tickers=("ADB",),
                    issuer="Adnams",
                    published_at=published,
                    title="Adnams raises funds for new brewery",
                    document_type="news",
                    url="https://example.com/y",
                    collected_at=published,
                    raw_metadata={},
                    market="aq",
                    effective_at=published,
                ),
                InformationItem(
                    source="google_news_aq",
                    source_type="news",
                    external_id="g-1",
                    tickers=("ADB",),
                    issuer="Adnams",
                    published_at=published,
                    title="Adnams raises funds for new brewery",
                    document_type="news",
                    url="https://example.com/g",
                    collected_at=published,
                    raw_metadata={},
                    market="aq",
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
                {("Google News (AQ)",), ("Yahoo Finance AQ",)},
            )


if __name__ == "__main__":
    unittest.main()
