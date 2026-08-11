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
    title: str = "AB InBev reports record quarterly profit",
    ticker: str = "ABI",
    market: str = "be",
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


class BeDedupeKeyTests(unittest.TestCase):
    def test_be_market_key_is_non_empty_for_news(self) -> None:
        item = feed_item("yahoo_be", "y-1")

        self.assertIsNotNone(dedupe_key(item))

    def test_be_news_folds_across_sources_by_ticker_day_title(self) -> None:
        first = feed_item("yahoo_be", "y-1")
        second = feed_item("google_news_be", "g-1")

        self.assertEqual(dedupe_key(first), dedupe_key(second))
        self.assertTrue(dedupe_key(first).startswith("be-news:"))
        self.assertIn("ABI|2026-08-05|", dedupe_key(first))

    def test_be_news_different_day_does_not_fold(self) -> None:
        first = feed_item(
            "yahoo_be",
            "y-1",
            published=datetime(2026, 8, 5, 10, 0, tzinfo=timezone.utc),
        )
        second = feed_item(
            "google_news_be",
            "g-1",
            published=datetime(2026, 8, 6, 10, 0, tzinfo=timezone.utc),
        )

        self.assertNotEqual(dedupe_key(first), dedupe_key(second))

    def test_be_news_different_title_does_not_fold(self) -> None:
        first = feed_item(
            "yahoo_be",
            "y-1",
            title="AB InBev reports record quarterly profit",
        )
        second = feed_item(
            "google_news_be",
            "g-1",
            title="Brussels shares close higher",
        )

        self.assertNotEqual(dedupe_key(first), dedupe_key(second))

    def test_be_news_different_ticker_does_not_fold(self) -> None:
        first = feed_item("yahoo_be", "y-1", ticker="ABI")
        second = feed_item("google_news_be", "g-1", ticker="KBC")

        self.assertNotEqual(dedupe_key(first), dedupe_key(second))

    def test_brussels_day_uses_europe_brussels_timezone(self) -> None:
        late_utc = feed_item(
            "yahoo_be",
            "y-1",
            published=datetime(2026, 8, 5, 23, 30, tzinfo=timezone.utc),
        )
        early_utc = feed_item(
            "google_news_be",
            "g-1",
            published=datetime(2026, 8, 5, 13, 0, tzinfo=timezone.utc),
        )

        # 23:30 UTC = 01:30 CEST next day; 13:00 UTC = 15:00 CEST same day.
        self.assertIn("2026-08-06", dedupe_key(late_utc))
        self.assertIn("2026-08-05", dedupe_key(early_utc))

    def test_be_filing_same_external_id_pairs(self) -> None:
        first = feed_item(
            "fsma_stori",
            "73f3a9ba-6003-4506-900b-50bc834927d6",
            source_type="regulatory_filing",
        )
        second = feed_item(
            "fsma_stori",
            "73f3a9ba-6003-4506-900b-50bc834927d6",
            source_type="regulatory_filing",
        )

        self.assertEqual(dedupe_key(first), dedupe_key(second))
        self.assertTrue(dedupe_key(first).startswith("be:filing:stori:"))

    def test_be_filing_title_fallback_is_source_scoped(self) -> None:
        title = "AB InBev reports Half-Year results"
        first = feed_item(
            "fsma_stori",
            "",
            source_type="regulatory_filing",
            title=title,
        )
        second = feed_item(
            "hypothetical_second_source",
            "",
            source_type="regulatory_filing",
            title=title,
        )

        self.assertTrue(
            dedupe_key(first).startswith("be:filing:title:fsma_stori:")
        )
        self.assertNotEqual(dedupe_key(first), dedupe_key(second))

    def test_us_market_still_has_no_key(self) -> None:
        item = feed_item("sec", "sec-1", market="us")

        self.assertIsNone(dedupe_key(item))


class BeAnnotateTests(unittest.TestCase):
    def test_news_same_key_keeps_both_rows_annotated(self) -> None:
        first = feed_item("yahoo_be", "y-1")
        second = feed_item("google_news_be", "g-1")

        annotated = annotate_feed_items([first, second])

        self.assertEqual(len(annotated), 2)
        self.assertEqual(annotated[0]["also_seen_on"], ["google_news_be"])
        self.assertEqual(
            annotated[0]["also_seen_on_labels"],
            ["Google News (BE)"],
        )
        self.assertEqual(annotated[1]["also_seen_on"], ["yahoo_be"])
        self.assertEqual(
            annotated[1]["also_seen_on_labels"],
            ["Yahoo Finance BE"],
        )
        self.assertEqual(annotated[0]["dedupe_count"], 2)

    def test_filing_same_external_id_is_annotated_with_label(self) -> None:
        first = feed_item(
            "fsma_stori",
            "73f3a9ba-6003-4506-900b-50bc834927d6",
            source_type="regulatory_filing",
        )
        second = feed_item(
            "fsma_stori",
            "73f3a9ba-6003-4506-900b-50bc834927d6",
            source_type="regulatory_filing",
        )

        annotated = annotate_feed_items([first, second])

        self.assertEqual(len(annotated), 2)
        self.assertEqual(annotated[0]["also_seen_on"], ["fsma_stori"])
        self.assertEqual(
            annotated[0]["also_seen_on_labels"],
            ["FSMA STORI"],
        )

    def test_switch_off_returns_all_rows_without_annotations(self) -> None:
        first = feed_item("yahoo_be", "y-1")
        second = feed_item("google_news_be", "g-1")

        annotated = annotate_feed_items([first, second], enabled=False)

        self.assertEqual(len(annotated), 2)
        self.assertNotIn("also_seen_on", annotated[0])
        self.assertNotIn("also_seen_on", annotated[1])

    def test_cross_source_news_different_title_is_not_annotated(self) -> None:
        first = feed_item("yahoo_be", "y-1", title="AB InBev reports profit")
        second = feed_item(
            "google_news_be",
            "g-1",
            title="Brussels shares close higher",
        )

        annotated = annotate_feed_items([first, second])

        self.assertEqual(len(annotated), 2)
        self.assertNotIn("also_seen_on", annotated[0])
        self.assertNotIn("also_seen_on", annotated[1])


class WebRepositoryBeDedupeTests(unittest.TestCase):
    def test_display_annotates_be_news_while_raw_keeps_rows(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            database_path = Path(temporary_directory) / "web.sqlite3"
            items = SQLiteInformationRepository(database_path)
            repository = WebRepository(
                database_path,
                allowed_sources=("yahoo_be", "google_news_be"),
                known_sources=(
                    SourceConfig(
                        "yahoo_be",
                        "Yahoo Finance BE",
                        "news",
                        True,
                    ),
                    SourceConfig(
                        "google_news_be",
                        "Google News (BE)",
                        "news",
                        True,
                    ),
                ),
                implemented_sources=("yahoo_be", "google_news_be"),
            )
            repository.add_companies_batch(
                "ABI",
                ("holdings",),
                None,
                market="be",
            )
            published = datetime(2026, 8, 5, 10, 0, tzinfo=timezone.utc)
            items.save([
                InformationItem(
                    source="yahoo_be",
                    source_type="news",
                    external_id="y-1",
                    tickers=("ABI",),
                    issuer="ABI",
                    published_at=published,
                    title="AB InBev reports record quarterly profit",
                    document_type="news",
                    url="https://example.com/y",
                    collected_at=published,
                    raw_metadata={},
                    market="be",
                    effective_at=published,
                ),
                InformationItem(
                    source="google_news_be",
                    source_type="news",
                    external_id="g-1",
                    tickers=("ABI",),
                    issuer="ABI",
                    published_at=published,
                    title="AB InBev reports record quarterly profit",
                    document_type="news",
                    url="https://example.com/g",
                    collected_at=published,
                    raw_metadata={},
                    market="be",
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
                {("Google News (BE)",), ("Yahoo Finance BE",)},
            )


if __name__ == "__main__":
    unittest.main()
