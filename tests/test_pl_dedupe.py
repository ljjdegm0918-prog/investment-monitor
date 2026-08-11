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
    title: str = "PKO Bank Polski raportuje rekordowy zysk",
    ticker: str = "PKO",
    market: str = "pl",
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


class PlDedupeKeyTests(unittest.TestCase):
    def test_pl_market_key_is_non_empty_for_news(self) -> None:
        item = feed_item("yahoo_pl", "y-1")

        self.assertIsNotNone(dedupe_key(item))

    def test_pl_news_folds_across_sources_by_ticker_day_title(self) -> None:
        first = feed_item("yahoo_pl", "y-1")
        second = feed_item("google_news_pl", "g-1")

        self.assertEqual(dedupe_key(first), dedupe_key(second))
        self.assertTrue(dedupe_key(first).startswith("pl-news:"))
        self.assertIn("PKO|2026-08-05|", dedupe_key(first))

    def test_pl_news_different_day_does_not_fold(self) -> None:
        first = feed_item(
            "yahoo_pl",
            "y-1",
            published=datetime(2026, 8, 5, 10, 0, tzinfo=timezone.utc),
        )
        second = feed_item(
            "google_news_pl",
            "g-1",
            published=datetime(2026, 8, 6, 10, 0, tzinfo=timezone.utc),
        )

        self.assertNotEqual(dedupe_key(first), dedupe_key(second))

    def test_pl_news_different_title_does_not_fold(self) -> None:
        first = feed_item(
            "yahoo_pl",
            "y-1",
            title="PKO raportuje zysk",
        )
        second = feed_item(
            "google_news_pl",
            "g-1",
            title="Banki na GPW rosna",
        )

        self.assertNotEqual(dedupe_key(first), dedupe_key(second))

    def test_pl_news_different_ticker_does_not_fold(self) -> None:
        first = feed_item("yahoo_pl", "y-1", ticker="PKO")
        second = feed_item("google_news_pl", "g-1", ticker="PKN")

        self.assertNotEqual(dedupe_key(first), dedupe_key(second))

    def test_warsaw_day_uses_poland_timezone(self) -> None:
        late_utc = feed_item(
            "yahoo_pl",
            "y-1",
            published=datetime(2026, 8, 5, 23, 30, tzinfo=timezone.utc),
        )
        early_utc = feed_item(
            "google_news_pl",
            "g-1",
            published=datetime(2026, 8, 6, 4, 0, tzinfo=timezone.utc),
        )

        # 23:30 UTC on 5 Aug is already 6 Aug in Warsaw (CEST, UTC+2).
        self.assertIn("2026-08-06", dedupe_key(late_utc))
        self.assertIn("2026-08-06", dedupe_key(early_utc))

    def test_pl_filing_pairs_on_stable_gpw_report_id(self) -> None:
        first = feed_item(
            "gpw_espi",
            "495125",
            source_type="regulatory_filing",
        )
        second = feed_item(
            "gpw_espi",
            "495125",
            source_type="regulatory_filing",
        )

        self.assertEqual(dedupe_key(first), dedupe_key(second))
        self.assertEqual(dedupe_key(first), "pl:filing:gpw:495125")

    def test_pl_filing_different_report_id_does_not_fold(self) -> None:
        first = feed_item(
            "gpw_espi",
            "495125",
            source_type="regulatory_filing",
        )
        second = feed_item(
            "gpw_espi",
            "495124",
            source_type="regulatory_filing",
        )

        self.assertNotEqual(dedupe_key(first), dedupe_key(second))

    def test_pl_filing_title_fallback_is_source_scoped(self) -> None:
        first = feed_item(
            "gpw_espi",
            "",
            source_type="regulatory_filing",
            title="Zmiana statutu",
        )
        second = feed_item(
            "eqs_pl",
            "",
            source_type="regulatory_filing",
            title="Zmiana statutu",
        )

        self.assertIsNotNone(dedupe_key(first))
        self.assertTrue(dedupe_key(first).startswith("pl:filing:title:gpw_espi:"))
        self.assertNotEqual(dedupe_key(first), dedupe_key(second))

    def test_us_market_still_has_no_key(self) -> None:
        item = feed_item("sec", "sec-1", market="us")

        self.assertIsNone(dedupe_key(item))


class PlAnnotateTests(unittest.TestCase):
    def test_news_same_key_keeps_both_rows_annotated(self) -> None:
        first = feed_item("yahoo_pl", "y-1")
        second = feed_item("google_news_pl", "g-1")

        annotated = annotate_feed_items([first, second])

        self.assertEqual(len(annotated), 2)
        self.assertEqual(annotated[0]["also_seen_on"], ["google_news_pl"])
        self.assertEqual(
            annotated[0]["also_seen_on_labels"],
            ["Google News (PL)"],
        )
        self.assertEqual(annotated[1]["also_seen_on"], ["yahoo_pl"])
        self.assertEqual(
            annotated[1]["also_seen_on_labels"],
            ["Yahoo Finance PL"],
        )
        self.assertEqual(annotated[0]["dedupe_count"], 2)

    def test_switch_off_returns_all_rows_without_annotations(self) -> None:
        first = feed_item("yahoo_pl", "y-1")
        second = feed_item("google_news_pl", "g-1")

        annotated = annotate_feed_items([first, second], enabled=False)

        self.assertEqual(len(annotated), 2)
        self.assertNotIn("also_seen_on", annotated[0])
        self.assertNotIn("also_seen_on", annotated[1])

    def test_cross_source_news_different_title_is_not_annotated(self) -> None:
        first = feed_item("yahoo_pl", "y-1", title="PKO raportuje zysk")
        second = feed_item(
            "google_news_pl",
            "g-1",
            title="Banki na GPW rosna",
        )

        annotated = annotate_feed_items([first, second])

        self.assertEqual(len(annotated), 2)
        self.assertNotIn("also_seen_on", annotated[0])
        self.assertNotIn("also_seen_on", annotated[1])


class WebRepositoryPlDedupeTests(unittest.TestCase):
    def test_display_annotates_pl_news_while_raw_keeps_rows(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            database_path = Path(temporary_directory) / "web.sqlite3"
            items = SQLiteInformationRepository(database_path)
            repository = WebRepository(
                database_path,
                allowed_sources=("yahoo_pl", "google_news_pl"),
                known_sources=(
                    SourceConfig(
                        "yahoo_pl",
                        "Yahoo Finance PL",
                        "news",
                        True,
                    ),
                    SourceConfig(
                        "google_news_pl",
                        "Google News (PL)",
                        "news",
                        True,
                    ),
                ),
                implemented_sources=("yahoo_pl", "google_news_pl"),
            )
            repository.add_companies_batch(
                "PKO",
                ("holdings",),
                None,
                market="pl",
            )
            published = datetime(2026, 8, 5, 10, 0, tzinfo=timezone.utc)
            items.save([
                InformationItem(
                    source="yahoo_pl",
                    source_type="news",
                    external_id="y-1",
                    tickers=("PKO",),
                    issuer="PKO",
                    published_at=published,
                    title="PKO Bank Polski raportuje rekordowy zysk",
                    document_type="news",
                    url="https://example.com/y",
                    collected_at=published,
                    raw_metadata={},
                    market="pl",
                    effective_at=published,
                ),
                InformationItem(
                    source="google_news_pl",
                    source_type="news",
                    external_id="g-1",
                    tickers=("PKO",),
                    issuer="PKO",
                    published_at=published,
                    title="PKO Bank Polski raportuje rekordowy zysk",
                    document_type="news",
                    url="https://example.com/g",
                    collected_at=published,
                    raw_metadata={},
                    market="pl",
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
                {("Google News (PL)",), ("Yahoo Finance PL",)},
            )


if __name__ == "__main__":
    unittest.main()
