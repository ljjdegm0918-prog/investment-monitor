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
    title: str = "AstraZeneca announces new oncology data",
    ticker: str = "AZNL",
    market: str = "cxe",
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


class CxeDedupeKeyTests(unittest.TestCase):
    def test_cxe_news_key_is_non_empty(self) -> None:
        item = feed_item("google_news_cxe", "g-1")

        self.assertIsNotNone(dedupe_key(item))
        self.assertTrue(dedupe_key(item).startswith("cxe-news:"))
        self.assertIn("AZNL|2026-08-05|", dedupe_key(item))

    def test_same_ticker_day_title_shares_key(self) -> None:
        first = feed_item("google_news_cxe", "g-1")
        second = feed_item("google_news_cxe", "g-2")

        self.assertEqual(dedupe_key(first), dedupe_key(second))

    def test_different_day_does_not_fold(self) -> None:
        first = feed_item(
            "google_news_cxe",
            "g-1",
            published=datetime(2026, 8, 5, 10, 0, tzinfo=timezone.utc),
        )
        second = feed_item(
            "google_news_cxe",
            "g-2",
            published=datetime(2026, 8, 6, 10, 0, tzinfo=timezone.utc),
        )

        self.assertNotEqual(dedupe_key(first), dedupe_key(second))

    def test_different_title_does_not_fold(self) -> None:
        first = feed_item("google_news_cxe", "g-1", title="Oncology data")
        second = feed_item("google_news_cxe", "g-2", title="Pharma rally")

        self.assertNotEqual(dedupe_key(first), dedupe_key(second))

    def test_different_ticker_does_not_fold(self) -> None:
        first = feed_item("google_news_cxe", "g-1", ticker="AZNL")
        second = feed_item("google_news_cxe", "g-2", ticker="SHELL")

        self.assertNotEqual(dedupe_key(first), dedupe_key(second))

    def test_london_day_uses_british_timezone(self) -> None:
        late_utc = feed_item(
            "google_news_cxe",
            "g-1",
            published=datetime(2026, 8, 9, 23, 30, tzinfo=timezone.utc),
        )
        evening_utc = feed_item(
            "google_news_cxe",
            "g-2",
            published=datetime(2026, 8, 10, 21, 0, tzinfo=timezone.utc),
        )
        next_day_utc = feed_item(
            "google_news_cxe",
            "g-3",
            published=datetime(2026, 8, 10, 23, 30, tzinfo=timezone.utc),
        )

        self.assertIn("2026-08-10", dedupe_key(late_utc))
        self.assertEqual(dedupe_key(late_utc), dedupe_key(evening_utc))
        self.assertIn("2026-08-11", dedupe_key(next_day_utc))
        self.assertNotEqual(dedupe_key(late_utc), dedupe_key(next_day_utc))

    def test_cxe_filing_never_gets_a_key(self) -> None:
        item = feed_item(
            "cxe_disclosure",
            "f-1",
            source_type="regulatory_filing",
        )

        self.assertIsNone(dedupe_key(item))

    def test_non_cxe_markets_still_use_their_own_rules(self) -> None:
        aq = feed_item(
            "yahoo_aq",
            "aq-1",
            market="aq",
            title="Adnams brewery",
        )
        uk = feed_item(
            "yahoo_uk",
            "uk-1",
            market="uk",
            title="London headlines",
        )

        self.assertTrue(dedupe_key(aq).startswith("aq-news:"))
        self.assertTrue(dedupe_key(uk).startswith("uk-news:"))


class CxeAnnotateFeedItemsTests(unittest.TestCase):
    def test_same_key_keeps_both_rows_annotated(self) -> None:
        first = feed_item("google_news_cxe", "g-1")
        second = feed_item("google_news_cxe", "g-2")

        annotated = annotate_feed_items([first, second])

        self.assertEqual(len(annotated), 2)
        self.assertEqual(annotated[0]["also_seen_on"], ["google_news_cxe"])
        self.assertEqual(
            annotated[0]["also_seen_on_labels"],
            ["Google News (CXE)"],
        )
        self.assertEqual(annotated[0]["dedupe_count"], 2)

    def test_switch_off_returns_all_rows_without_annotations(self) -> None:
        first = feed_item("google_news_cxe", "g-1")
        second = feed_item("google_news_cxe", "g-2")

        annotated = annotate_feed_items([first, second], enabled=False)

        self.assertEqual(len(annotated), 2)
        self.assertNotIn("also_seen_on", annotated[0])
        self.assertNotIn("also_seen_on", annotated[1])


class WebRepositoryCxeDedupeTests(unittest.TestCase):
    def test_display_annotates_cxe_news_while_raw_keeps_rows(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            database_path = Path(temporary_directory) / "web.sqlite3"
            items = SQLiteInformationRepository(database_path)
            repository = WebRepository(
                database_path,
                allowed_sources=("google_news_cxe",),
                known_sources=(
                    SourceConfig(
                        "google_news_cxe",
                        "Google News (CXE)",
                        "news",
                        True,
                    ),
                ),
                implemented_sources=("google_news_cxe",),
            )
            repository.add_companies_batch(
                "AZNL",
                ("holdings",),
                None,
                market="cxe",
            )
            published = datetime(2026, 8, 5, 10, 0, tzinfo=timezone.utc)
            items.save([
                InformationItem(
                    source="google_news_cxe",
                    source_type="news",
                    external_id="g-1",
                    tickers=("AZNL",),
                    issuer="AstraZeneca PLC",
                    published_at=published,
                    title="AstraZeneca announces new oncology data",
                    document_type="news",
                    url="https://example.com/g1",
                    collected_at=published,
                    raw_metadata={},
                    market="cxe",
                    effective_at=published,
                ),
                InformationItem(
                    source="google_news_cxe",
                    source_type="news",
                    external_id="g-2",
                    tickers=("AZNL",),
                    issuer="AstraZeneca PLC",
                    published_at=published,
                    title="AstraZeneca announces new oncology data",
                    document_type="news",
                    url="https://example.com/g2",
                    collected_at=published,
                    raw_metadata={},
                    market="cxe",
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
            self.assertEqual(labels, {("Google News (CXE)",)})


if __name__ == "__main__":
    unittest.main()
