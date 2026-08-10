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
    title: str = "DAX Futures steigen vor Zinsentscheid",
    ticker: str = "FDAX",
    market: str = "eux",
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


class EuxDedupeKeyTests(unittest.TestCase):
    def test_eux_news_key_is_non_empty(self) -> None:
        item = feed_item("google_news_eux", "g-1")

        self.assertIsNotNone(dedupe_key(item))
        self.assertTrue(dedupe_key(item).startswith("eux-news:"))
        self.assertIn("FDAX|2026-08-05|", dedupe_key(item))

    def test_same_code_day_title_shares_key(self) -> None:
        first = feed_item("google_news_eux", "g-1")
        second = feed_item("google_news_eux", "g-2")

        self.assertEqual(dedupe_key(first), dedupe_key(second))

    def test_different_day_does_not_fold(self) -> None:
        first = feed_item(
            "google_news_eux",
            "g-1",
            published=datetime(2026, 8, 5, 10, 0, tzinfo=timezone.utc),
        )
        second = feed_item(
            "google_news_eux",
            "g-2",
            published=datetime(2026, 8, 6, 10, 0, tzinfo=timezone.utc),
        )

        self.assertNotEqual(dedupe_key(first), dedupe_key(second))

    def test_different_title_does_not_fold(self) -> None:
        first = feed_item("google_news_eux", "g-1", title="DAX Futures rally")
        second = feed_item("google_news_eux", "g-2", title="Eurex volumes")

        self.assertNotEqual(dedupe_key(first), dedupe_key(second))

    def test_different_product_code_does_not_fold(self) -> None:
        first = feed_item("google_news_eux", "g-1", ticker="FDAX")
        second = feed_item("google_news_eux", "g-2", ticker="FGBL")

        self.assertNotEqual(dedupe_key(first), dedupe_key(second))

    def test_berlin_day_uses_frankfurt_timezone(self) -> None:
        # 22:30 UTC on 2026-08-09 is 00:30 CEST on 2026-08-10 (same
        # Berlin day as 21:00 UTC on 2026-08-10); 22:30 UTC on 2026-08-10
        # is 00:30 CEST on 2026-08-11.
        late_utc = feed_item(
            "google_news_eux",
            "g-1",
            published=datetime(2026, 8, 9, 22, 30, tzinfo=timezone.utc),
        )
        evening_utc = feed_item(
            "google_news_eux",
            "g-2",
            published=datetime(2026, 8, 10, 21, 0, tzinfo=timezone.utc),
        )
        next_day_utc = feed_item(
            "google_news_eux",
            "g-3",
            published=datetime(2026, 8, 10, 22, 30, tzinfo=timezone.utc),
        )

        self.assertIn("2026-08-10", dedupe_key(late_utc))
        self.assertEqual(dedupe_key(late_utc), dedupe_key(evening_utc))
        self.assertIn("2026-08-11", dedupe_key(next_day_utc))
        self.assertNotEqual(dedupe_key(late_utc), dedupe_key(next_day_utc))

    def test_eux_filing_never_gets_a_key(self) -> None:
        item = feed_item(
            "eux_disclosure",
            "f-1",
            source_type="regulatory_filing",
        )

        self.assertIsNone(dedupe_key(item))

    def test_non_eux_markets_still_use_their_own_rules(self) -> None:
        trq = feed_item(
            "google_news_trq",
            "trq-1",
            market="trq",
            title="AstraZeneca oncology",
        )
        de = feed_item(
            "yahoo_de",
            "de-1",
            market="de",
            title="SAP results",
        )

        self.assertTrue(dedupe_key(trq).startswith("trq-news:"))
        self.assertTrue(dedupe_key(de).startswith("de-news:"))


class EuxAnnotateFeedItemsTests(unittest.TestCase):
    def test_same_key_keeps_both_rows_annotated(self) -> None:
        first = feed_item("google_news_eux", "g-1")
        second = feed_item("google_news_eux", "g-2")

        annotated = annotate_feed_items([first, second])

        self.assertEqual(len(annotated), 2)
        self.assertEqual(annotated[0]["also_seen_on"], ["google_news_eux"])
        self.assertEqual(
            annotated[0]["also_seen_on_labels"],
            ["Google News (EUX)"],
        )
        self.assertEqual(annotated[0]["dedupe_count"], 2)

    def test_switch_off_returns_all_rows_without_annotations(self) -> None:
        first = feed_item("google_news_eux", "g-1")
        second = feed_item("google_news_eux", "g-2")

        annotated = annotate_feed_items([first, second], enabled=False)

        self.assertEqual(len(annotated), 2)
        self.assertNotIn("also_seen_on", annotated[0])
        self.assertNotIn("also_seen_on", annotated[1])


class WebRepositoryEuxDedupeTests(unittest.TestCase):
    def test_display_annotates_eux_news_while_raw_keeps_rows(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            database_path = Path(temporary_directory) / "web.sqlite3"
            items = SQLiteInformationRepository(database_path)
            repository = WebRepository(
                database_path,
                allowed_sources=("google_news_eux",),
                known_sources=(
                    SourceConfig(
                        "google_news_eux",
                        "Google News (EUX)",
                        "news",
                        True,
                    ),
                ),
                implemented_sources=("google_news_eux",),
            )
            repository.add_companies_batch(
                "FDAX",
                ("holdings",),
                None,
                market="eux",
            )
            published = datetime(2026, 8, 5, 10, 0, tzinfo=timezone.utc)
            items.save([
                InformationItem(
                    source="google_news_eux",
                    source_type="news",
                    external_id="g-1",
                    tickers=("FDAX",),
                    issuer="DAX Futures",
                    published_at=published,
                    title="DAX Futures steigen vor Zinsentscheid",
                    document_type="news",
                    url="https://example.com/g1",
                    collected_at=published,
                    raw_metadata={},
                    market="eux",
                    effective_at=published,
                ),
                InformationItem(
                    source="google_news_eux",
                    source_type="news",
                    external_id="g-2",
                    tickers=("FDAX",),
                    issuer="DAX Futures",
                    published_at=published,
                    title="DAX Futures steigen vor Zinsentscheid",
                    document_type="news",
                    url="https://example.com/g2",
                    collected_at=published,
                    raw_metadata={},
                    market="eux",
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
            self.assertEqual(labels, {("Google News (EUX)",)})


if __name__ == "__main__":
    unittest.main()
