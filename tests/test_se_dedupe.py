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
    title: str = "Ericsson redovisar rekordkvartal",
    ticker: str = "ERIC-B",
    market: str = "se",
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


class SeDedupeKeyTests(unittest.TestCase):
    def test_se_market_key_is_non_empty_for_news(self) -> None:
        item = feed_item("yahoo_se", "y-1")

        self.assertIsNotNone(dedupe_key(item))

    def test_se_news_folds_across_sources_by_ticker_day_title(self) -> None:
        first = feed_item("yahoo_se", "y-1")
        second = feed_item("google_news_se", "g-1")

        self.assertEqual(dedupe_key(first), dedupe_key(second))
        self.assertTrue(dedupe_key(first).startswith("se-news:"))
        self.assertIn("ERIC-B|2026-08-05|", dedupe_key(first))

    def test_se_news_different_day_does_not_fold(self) -> None:
        first = feed_item(
            "yahoo_se",
            "y-1",
            published=datetime(2026, 8, 5, 10, 0, tzinfo=timezone.utc),
        )
        second = feed_item(
            "google_news_se",
            "g-1",
            published=datetime(2026, 8, 6, 10, 0, tzinfo=timezone.utc),
        )

        self.assertNotEqual(dedupe_key(first), dedupe_key(second))

    def test_se_news_different_title_does_not_fold(self) -> None:
        first = feed_item(
            "yahoo_se",
            "y-1",
            title="Ericsson redovisar rekordkvartal",
        )
        second = feed_item(
            "google_news_se",
            "g-1",
            title="Teknikaktier lyfter Stockholmsborsen",
        )

        self.assertNotEqual(dedupe_key(first), dedupe_key(second))

    def test_se_news_different_ticker_does_not_fold(self) -> None:
        first = feed_item("yahoo_se", "y-1", ticker="ERIC-B")
        second = feed_item("google_news_se", "g-1", ticker="VOLV-B")

        self.assertNotEqual(dedupe_key(first), dedupe_key(second))

    def test_stockholm_day_uses_sweden_timezone(self) -> None:
        late_utc = feed_item(
            "yahoo_se",
            "y-1",
            published=datetime(2026, 8, 5, 23, 30, tzinfo=timezone.utc),
        )
        early_utc = feed_item(
            "google_news_se",
            "g-1",
            published=datetime(2026, 8, 6, 4, 0, tzinfo=timezone.utc),
        )

        # 23:30 UTC on 5 Aug is already 6 Aug in Stockholm (CEST, UTC+2).
        self.assertIn("2026-08-06", dedupe_key(late_utc))
        self.assertIn("2026-08-06", dedupe_key(early_utc))

    def test_se_filing_without_connector_has_no_key(self) -> None:
        item = feed_item(
            "fi_oam",
            "f-1",
            source_type="regulatory_filing",
        )

        self.assertIsNone(dedupe_key(item))

    def test_us_market_still_has_no_key(self) -> None:
        item = feed_item("sec", "sec-1", market="us")

        self.assertIsNone(dedupe_key(item))


class SeAnnotateTests(unittest.TestCase):
    def test_news_same_key_keeps_both_rows_annotated(self) -> None:
        first = feed_item("yahoo_se", "y-1")
        second = feed_item("google_news_se", "g-1")

        annotated = annotate_feed_items([first, second])

        self.assertEqual(len(annotated), 2)
        self.assertEqual(annotated[0]["also_seen_on"], ["google_news_se"])
        self.assertEqual(
            annotated[0]["also_seen_on_labels"],
            ["Google News (SE)"],
        )
        self.assertEqual(annotated[1]["also_seen_on"], ["yahoo_se"])
        self.assertEqual(
            annotated[1]["also_seen_on_labels"],
            ["Yahoo Finance SE"],
        )
        self.assertEqual(annotated[0]["dedupe_count"], 2)

    def test_switch_off_returns_all_rows_without_annotations(self) -> None:
        first = feed_item("yahoo_se", "y-1")
        second = feed_item("google_news_se", "g-1")

        annotated = annotate_feed_items([first, second], enabled=False)

        self.assertEqual(len(annotated), 2)
        self.assertNotIn("also_seen_on", annotated[0])
        self.assertNotIn("also_seen_on", annotated[1])

    def test_cross_source_news_different_title_is_not_annotated(self) -> None:
        first = feed_item(
            "yahoo_se",
            "y-1",
            title="Ericsson redovisar rekordkvartal",
        )
        second = feed_item(
            "google_news_se",
            "g-1",
            title="Teknikaktier lyfter Stockholmsborsen",
        )

        annotated = annotate_feed_items([first, second])

        self.assertEqual(len(annotated), 2)
        self.assertNotIn("also_seen_on", annotated[0])
        self.assertNotIn("also_seen_on", annotated[1])


class WebRepositorySeDedupeTests(unittest.TestCase):
    def test_display_annotates_se_news_while_raw_keeps_rows(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            database_path = Path(temporary_directory) / "web.sqlite3"
            items = SQLiteInformationRepository(database_path)
            repository = WebRepository(
                database_path,
                allowed_sources=("yahoo_se", "google_news_se"),
                known_sources=(
                    SourceConfig(
                        "yahoo_se",
                        "Yahoo Finance SE",
                        "news",
                        True,
                    ),
                    SourceConfig(
                        "google_news_se",
                        "Google News (SE)",
                        "news",
                        True,
                    ),
                ),
                implemented_sources=("yahoo_se", "google_news_se"),
            )
            repository.add_companies_batch(
                "ERIC-B",
                ("holdings",),
                None,
                market="se",
            )
            published = datetime(2026, 8, 5, 10, 0, tzinfo=timezone.utc)
            items.save([
                InformationItem(
                    source="yahoo_se",
                    source_type="news",
                    external_id="y-1",
                    tickers=("ERIC-B",),
                    issuer="ERIC-B",
                    published_at=published,
                    title="Ericsson redovisar rekordkvartal",
                    document_type="news",
                    url="https://example.com/y",
                    collected_at=published,
                    raw_metadata={},
                    market="se",
                    effective_at=published,
                ),
                InformationItem(
                    source="google_news_se",
                    source_type="news",
                    external_id="g-1",
                    tickers=("ERIC-B",),
                    issuer="ERIC-B",
                    published_at=published,
                    title="Ericsson redovisar rekordkvartal",
                    document_type="news",
                    url="https://example.com/g",
                    collected_at=published,
                    raw_metadata={},
                    market="se",
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
                {("Google News (SE)",), ("Yahoo Finance SE",)},
            )


if __name__ == "__main__":
    unittest.main()
