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
    title: str = "DBS reports record quarterly profit",
    ticker: str = "D05",
    market: str = "sg",
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


class SgDedupeKeyTests(unittest.TestCase):
    def test_sg_market_key_is_non_empty_for_news(self) -> None:
        item = feed_item("yahoo_sg", "y-1")

        self.assertIsNotNone(dedupe_key(item))

    def test_sg_news_folds_across_sources_by_ticker_day_title(self) -> None:
        first = feed_item("yahoo_sg", "y-1")
        second = feed_item("google_news_sg", "g-1")

        self.assertEqual(dedupe_key(first), dedupe_key(second))
        self.assertTrue(dedupe_key(first).startswith("sg-news:"))
        self.assertIn("D05|2026-08-05|", dedupe_key(first))

    def test_sg_news_different_day_does_not_fold(self) -> None:
        first = feed_item(
            "yahoo_sg",
            "y-1",
            published=datetime(2026, 8, 5, 10, 0, tzinfo=timezone.utc),
        )
        second = feed_item(
            "google_news_sg",
            "g-1",
            published=datetime(2026, 8, 6, 10, 0, tzinfo=timezone.utc),
        )

        self.assertNotEqual(dedupe_key(first), dedupe_key(second))

    def test_sg_news_different_title_does_not_fold(self) -> None:
        first = feed_item(
            "yahoo_sg", "y-1", title="DBS reports record quarterly profit"
        )
        second = feed_item(
            "google_news_sg", "g-1", title="Singapore shares close higher"
        )

        self.assertNotEqual(dedupe_key(first), dedupe_key(second))

    def test_sg_news_different_ticker_does_not_fold(self) -> None:
        first = feed_item("yahoo_sg", "y-1", ticker="D05")
        second = feed_item("google_news_sg", "g-1", ticker="U11")

        self.assertNotEqual(dedupe_key(first), dedupe_key(second))

    def test_singapore_day_uses_asia_singapore_timezone(self) -> None:
        late_utc = feed_item(
            "yahoo_sg",
            "y-1",
            published=datetime(2026, 8, 5, 18, 30, tzinfo=timezone.utc),
        )
        early_utc = feed_item(
            "google_news_sg",
            "g-1",
            published=datetime(2026, 8, 5, 3, 0, tzinfo=timezone.utc),
        )

        # 18:30 UTC = 02:30 SGT next day; 03:00 UTC = 11:00 SGT same day.
        self.assertIn("2026-08-06", dedupe_key(late_utc))
        self.assertIn("2026-08-05", dedupe_key(early_utc))

    def test_sg_official_filing_uses_announcement_reference(self) -> None:
        item = feed_item(
            "sgx_announcements",
            "a-1",
            source_type="regulatory_filing",
            raw_metadata={"announcement_reference": "SG260805OTHRABCD"},
        )

        self.assertEqual(
            dedupe_key(item), "sg:filing:sgx:SG260805OTHRABCD"
        )

    def test_sg_filing_shared_canonical_key_pairs_sources(self) -> None:
        sgx = feed_item(
            "sgx_announcements", "a-1", source_type="regulatory_filing",
            raw_metadata={"canonical_key": "sgx:SG260805OTHRABCD"},
        )
        ir = feed_item(
            "sg_ir", "ir-1", source_type="regulatory_filing",
            raw_metadata={"canonical_key": "sgx:SG260805OTHRABCD"},
        )
        self.assertEqual(dedupe_key(sgx), dedupe_key(ir))
        annotated = annotate_feed_items([sgx, ir])
        self.assertEqual(annotated[0]["also_seen_on"], ["sg_ir"])

    def test_us_market_still_has_no_key(self) -> None:
        item = feed_item("sec", "sec-1", market="us")

        self.assertIsNone(dedupe_key(item))


class SgAnnotateTests(unittest.TestCase):
    def test_news_same_key_keeps_both_rows_annotated(self) -> None:
        first = feed_item("yahoo_sg", "y-1")
        second = feed_item("google_news_sg", "g-1")

        annotated = annotate_feed_items([first, second])

        self.assertEqual(len(annotated), 2)
        self.assertEqual(annotated[0]["also_seen_on"], ["google_news_sg"])
        self.assertEqual(
            annotated[0]["also_seen_on_labels"],
            ["Google News (SG)"],
        )
        self.assertEqual(annotated[1]["also_seen_on"], ["yahoo_sg"])
        self.assertEqual(
            annotated[1]["also_seen_on_labels"],
            ["Yahoo Finance SG"],
        )
        self.assertEqual(annotated[0]["dedupe_count"], 2)

    def test_switch_off_returns_all_rows_without_annotations(self) -> None:
        first = feed_item("yahoo_sg", "y-1")
        second = feed_item("google_news_sg", "g-1")

        annotated = annotate_feed_items([first, second], enabled=False)

        self.assertEqual(len(annotated), 2)
        self.assertNotIn("also_seen_on", annotated[0])
        self.assertNotIn("also_seen_on", annotated[1])

    def test_cross_source_news_different_title_is_not_annotated(self) -> None:
        first = feed_item("yahoo_sg", "y-1", title="DBS reports profit")
        second = feed_item(
            "google_news_sg", "g-1", title="Singapore shares close higher"
        )

        annotated = annotate_feed_items([first, second])

        self.assertEqual(len(annotated), 2)
        self.assertNotIn("also_seen_on", annotated[0])
        self.assertNotIn("also_seen_on", annotated[1])


class WebRepositorySgDedupeTests(unittest.TestCase):
    def test_display_annotates_sg_news_while_raw_keeps_rows(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            database_path = Path(temporary_directory) / "web.sqlite3"
            items = SQLiteInformationRepository(database_path)
            repository = WebRepository(
                database_path,
                allowed_sources=("yahoo_sg", "google_news_sg"),
                known_sources=(
                    SourceConfig(
                        "yahoo_sg",
                        "Yahoo Finance SG",
                        "news",
                        True,
                    ),
                    SourceConfig(
                        "google_news_sg",
                        "Google News (SG)",
                        "news",
                        True,
                    ),
                ),
                implemented_sources=("yahoo_sg", "google_news_sg"),
            )
            repository.add_companies_batch(
                "D05",
                ("holdings",),
                None,
                market="sg",
            )
            published = datetime(2026, 8, 5, 10, 0, tzinfo=timezone.utc)
            items.save([
                InformationItem(
                    source="yahoo_sg",
                    source_type="news",
                    external_id="y-1",
                    tickers=("D05",),
                    issuer="D05",
                    published_at=published,
                    title="DBS reports record quarterly profit",
                    document_type="news",
                    url="https://example.com/y",
                    collected_at=published,
                    raw_metadata={},
                    market="sg",
                    effective_at=published,
                ),
                InformationItem(
                    source="google_news_sg",
                    source_type="news",
                    external_id="g-1",
                    tickers=("D05",),
                    issuer="D05",
                    published_at=published,
                    title="DBS reports record quarterly profit",
                    document_type="news",
                    url="https://example.com/g",
                    collected_at=published,
                    raw_metadata={},
                    market="sg",
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
                {("Google News (SG)",), ("Yahoo Finance SG",)},
            )


if __name__ == "__main__":
    unittest.main()
