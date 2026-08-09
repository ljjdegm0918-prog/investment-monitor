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
    title: str = "董事會決議日期",
    ticker: str = "2330",
    market: str = "tw",
    source_type: str = "regulatory_filing",
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


class TwDedupeKeyTests(unittest.TestCase):
    def test_tw_filing_same_source_same_day_title_folds(self) -> None:
        first = feed_item("twse_material", "")
        second = feed_item("twse_material", "", title="董事會決議日期 ")

        self.assertEqual(dedupe_key(first), dedupe_key(second))
        self.assertTrue(
            dedupe_key(first).startswith("tw:filing:title:twse_material:")
        )

    def test_tw_filing_tpex_prefix_is_source_scoped(self) -> None:
        item = feed_item("tpex_material", "")

        self.assertTrue(
            dedupe_key(item).startswith("tw:filing:title:tpex_material:")
        )

    def test_twse_and_tpex_same_title_never_cross_fold(self) -> None:
        title = "董事會決議日期"
        twse = feed_item("twse_material", "", title=title)
        tpex = feed_item("tpex_material", "", title=title)

        self.assertNotEqual(dedupe_key(twse), dedupe_key(tpex))
        self.assertEqual(len(annotate_feed_items([twse, tpex])), 2)
        self.assertNotIn("also_seen_on", annotate_feed_items([twse, tpex])[0])

    def test_tw_filing_different_day_does_not_fold(self) -> None:
        first = feed_item(
            "twse_material",
            "",
            published=datetime(2026, 8, 5, 10, 0, tzinfo=timezone.utc),
        )
        second = feed_item(
            "twse_material",
            "",
            published=datetime(2026, 8, 6, 10, 0, tzinfo=timezone.utc),
        )

        self.assertNotEqual(dedupe_key(first), dedupe_key(second))

    def test_taipei_day_uses_taiwan_timezone(self) -> None:
        late_utc = feed_item(
            "twse_material",
            "",
            published=datetime(2026, 8, 5, 23, 30, tzinfo=timezone.utc),
        )

        self.assertIn("2026-08-06", dedupe_key(late_utc))

    def test_tw_news_folds_across_sources_by_ticker_day_title(self) -> None:
        first = feed_item(
            "yahoo_tw",
            "y-1",
            source_type="news",
            title="台積電法說會",
        )
        second = feed_item(
            "google_news_tw",
            "g-1",
            source_type="news",
            title="台積電法說會",
        )

        self.assertEqual(dedupe_key(first), dedupe_key(second))
        self.assertTrue(dedupe_key(first).startswith("tw-news:"))
        self.assertIn("2330|2026-08-05|", dedupe_key(first))

    def test_tw_market_key_is_non_empty(self) -> None:
        item = feed_item("twse_material", "")

        self.assertIsNotNone(dedupe_key(item))

    def test_us_market_still_has_no_key(self) -> None:
        item = feed_item("sec", "sec-1", market="us")

        self.assertIsNone(dedupe_key(item))


class TwFoldFeedItemsTests(unittest.TestCase):
    def test_news_same_key_keeps_both_rows_annotated(self) -> None:
        first = feed_item(
            "yahoo_tw",
            "y-1",
            source_type="news",
            title="台積電法說會",
        )
        second = feed_item(
            "google_news_tw",
            "g-1",
            source_type="news",
            title="台積電法說會",
        )

        annotated = annotate_feed_items([first, second])

        self.assertEqual(len(annotated), 2)
        self.assertEqual(annotated[0]["also_seen_on"], ["google_news_tw"])
        self.assertEqual(
            annotated[0]["also_seen_on_labels"],
            ["Google News (TW)"],
        )
        self.assertEqual(annotated[1]["also_seen_on"], ["yahoo_tw"])
        self.assertEqual(
            annotated[1]["also_seen_on_labels"],
            ["Yahoo Finance TW"],
        )
        self.assertEqual(annotated[0]["dedupe_count"], 2)

    def test_same_source_filing_same_title_annotates(self) -> None:
        first = feed_item("twse_material", "")
        second = feed_item("twse_material", "", title="董事會決議日期 ")

        annotated = annotate_feed_items([first, second])

        self.assertEqual(len(annotated), 2)
        self.assertEqual(annotated[0]["also_seen_on"], ["twse_material"])
        self.assertEqual(
            annotated[0]["also_seen_on_labels"],
            ["TWSE OpenAPI (material)"],
        )

    def test_cross_source_filing_same_title_is_not_annotated(self) -> None:
        title = "董事會決議日期"
        twse = feed_item("twse_material", "", title=title)
        tpex = feed_item("tpex_material", "", title=title)

        annotated = annotate_feed_items([twse, tpex])

        self.assertEqual(len(annotated), 2)
        self.assertNotIn("also_seen_on", annotated[0])
        self.assertNotIn("also_seen_on", annotated[1])

    def test_switch_off_returns_all_rows_without_annotations(self) -> None:
        first = feed_item(
            "yahoo_tw",
            "y-1",
            source_type="news",
            title="台積電法說會",
        )
        second = feed_item(
            "google_news_tw",
            "g-1",
            source_type="news",
            title="台積電法說會",
        )

        annotated = annotate_feed_items([first, second], enabled=False)

        self.assertEqual(len(annotated), 2)
        self.assertNotIn("also_seen_on", annotated[0])
        self.assertNotIn("also_seen_on", annotated[1])


class WebRepositoryTwDedupeTests(unittest.TestCase):
    def test_display_annotates_tw_news_while_raw_keeps_rows(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            database_path = Path(temporary_directory) / "web.sqlite3"
            items = SQLiteInformationRepository(database_path)
            repository = WebRepository(
                database_path,
                allowed_sources=("yahoo_tw", "google_news_tw"),
                known_sources=(
                    SourceConfig(
                        "yahoo_tw",
                        "Yahoo Finance TW",
                        "news",
                        True,
                    ),
                    SourceConfig(
                        "google_news_tw",
                        "Google News (TW)",
                        "news",
                        True,
                    ),
                ),
                implemented_sources=("yahoo_tw", "google_news_tw"),
            )
            repository.add_companies_batch(
                "2330",
                ("holdings",),
                None,
                market="tw",
            )
            published = datetime(2026, 8, 5, 10, 0, tzinfo=timezone.utc)
            items.save([
                InformationItem(
                    source="yahoo_tw",
                    source_type="news",
                    external_id="y-1",
                    tickers=("2330",),
                    issuer="TSMC",
                    published_at=published,
                    title="台積電法說會",
                    document_type="news",
                    url="https://example.com/y",
                    collected_at=published,
                    raw_metadata={},
                    market="tw",
                    effective_at=published,
                ),
                InformationItem(
                    source="google_news_tw",
                    source_type="news",
                    external_id="g-1",
                    tickers=("2330",),
                    issuer="TSMC",
                    published_at=published,
                    title="台積電法說會",
                    document_type="news",
                    url="https://example.com/g",
                    collected_at=published,
                    raw_metadata={},
                    market="tw",
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
                {("Google News (TW)",), ("Yahoo Finance TW",)},
            )


if __name__ == "__main__":
    unittest.main()
