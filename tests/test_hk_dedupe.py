from datetime import date, datetime, timezone
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
    news_id: str = None,
    title: str = "Board Meeting Date",
    ticker: str = "00700",
    market: str = "hk",
    source_type: str = "regulatory_filing",
    published: datetime = None,
) -> dict:
    published = published or datetime(
        2026, 8, 5, 10, 0, tzinfo=timezone.utc
    )
    metadata = {}
    if news_id:
        metadata["news_id"] = news_id
    return {
        "source": source,
        "source_type": source_type,
        "external_id": external_id,
        "ticker": ticker,
        "market": market,
        "title": title,
        "published_at": published.isoformat(),
        "effective_at": published.isoformat(),
        "raw_metadata": metadata,
    }


class HkDedupeKeyTests(unittest.TestCase):
    def test_hkexnews_news_id_is_a_stable_key(self) -> None:
        item = feed_item(
            "hkexnews",
            "20260303001234",
            news_id="20260303001234",
        )

        self.assertEqual(
            dedupe_key(item),
            "hk:filing:news_id:20260303001234",
        )

    def test_different_hkexnews_news_ids_do_not_fold(self) -> None:
        first = feed_item(
            "hkexnews",
            "20260303001234",
            news_id="20260303001234",
        )
        second = feed_item(
            "hkexnews",
            "20260303001235",
            news_id="20260303001235",
        )

        self.assertNotEqual(dedupe_key(first), dedupe_key(second))

    def test_hkex_di_serial_is_a_stable_key(self) -> None:
        item = feed_item(
            "hkex_di",
            "20161003000123",
        )

        self.assertEqual(
            dedupe_key(item),
            "hk:filing:di:20161003000123",
        )

    def test_hkexnews_and_di_same_title_never_cross_fold(self) -> None:
        title = "Acquisition of shares"
        hkexnews = feed_item("hkexnews", "", title=title)
        di = feed_item("hkex_di", "", title=title)

        self.assertNotEqual(dedupe_key(hkexnews), dedupe_key(di))
        self.assertEqual(len(annotate_feed_items([hkexnews, di])), 2)

    def test_same_source_title_fallback_folds(self) -> None:
        first = feed_item("hkexnews", "", title="Board Meeting Date")
        second = feed_item("hkexnews", "", title="BOARD MEETING DATE")

        self.assertEqual(dedupe_key(first), dedupe_key(second))
        self.assertTrue(dedupe_key(first).startswith("hk:filing:title:hkexnews:"))

    def test_hkt_day_uses_hong_kong_timezone(self) -> None:
        late_utc = feed_item(
            "hkexnews",
            "",
            title="Board Meeting Date",
            published=datetime(2026, 8, 5, 23, 30, tzinfo=timezone.utc),
        )

        self.assertIn("2026-08-06", dedupe_key(late_utc))

    def test_hk_news_folds_by_ticker_hkt_day_title(self) -> None:
        first = feed_item(
            "yahoo_hk",
            "110000619",
            source_type="news",
            title="港股通淨流入",
        )
        second = feed_item(
            "yahoo_hk",
            "110000620",
            source_type="news",
            title="港股通淨流入",
        )

        self.assertEqual(dedupe_key(first), dedupe_key(second))
        self.assertTrue(dedupe_key(first).startswith("hk-news:"))
        self.assertIn("2026-08-05", dedupe_key(first))

    def test_us_market_still_has_no_key(self) -> None:
        item = feed_item("sec", "sec-1", market="us")

        self.assertIsNone(dedupe_key(item))


class HkFoldFeedItemsTests(unittest.TestCase):
    def test_same_news_id_keeps_both_rows_annotated(self) -> None:
        first = feed_item(
            "hkexnews",
            "20260303001234",
            news_id="20260303001234",
        )
        second = feed_item(
            "hkexnews",
            "20260303001234",
            news_id="20260303001234",
        )

        annotated = annotate_feed_items([first, second])

        self.assertEqual(len(annotated), 2)
        self.assertEqual(annotated[0]["source"], "hkexnews")
        self.assertEqual(annotated[0]["also_seen_on"], ["hkexnews"])
        self.assertEqual(
            annotated[0]["also_seen_on_labels"],
            ["HKEXnews (HKEX)"],
        )
        self.assertEqual(annotated[1]["also_seen_on"], ["hkexnews"])
        self.assertEqual(annotated[0]["dedupe_count"], 2)
        self.assertEqual(annotated[1]["dedupe_count"], 2)

    def test_cross_source_same_title_is_not_folded(self) -> None:
        title = "Acquisition of shares"
        hkexnews = feed_item("hkexnews", "", title=title)
        di = feed_item("hkex_di", "", title=title)

        annotated = annotate_feed_items([hkexnews, di])

        self.assertEqual(len(annotated), 2)
        self.assertNotIn("also_seen_on", annotated[0])
        self.assertNotIn("also_seen_on", annotated[1])

    def test_switch_off_returns_all_rows(self) -> None:
        first = feed_item(
            "hkexnews",
            "20260303001234",
            news_id="20260303001234",
        )
        second = feed_item(
            "hkexnews",
            "20260303001234",
            news_id="20260303001234",
        )

        annotated = annotate_feed_items([first, second], enabled=False)

        self.assertEqual(len(annotated), 2)
        self.assertNotIn("also_seen_on", annotated[0])


class WebRepositoryHkDedupeTests(unittest.TestCase):
    def test_display_folds_hk_while_raw_keeps_rows(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            database_path = Path(temporary_directory) / "web.sqlite3"
            items = SQLiteInformationRepository(database_path)
            repository = WebRepository(
                database_path,
                allowed_sources=("hkexnews",),
                known_sources=(
                    SourceConfig(
                        "hkexnews",
                        "HKEXnews (HKEX)",
                        "filings",
                        True,
                    ),
                ),
                implemented_sources=("hkexnews",),
            )
            repository.add_companies_batch(
                "00700",
                ("holdings",),
                None,
                market="hk",
            )
            published = datetime(2026, 8, 5, 10, 0, tzinfo=timezone.utc)
            items.save([
                InformationItem(
                    source="hkexnews",
                    source_type="regulatory_filing",
                    external_id="stable-hash-fallback",
                    tickers=("00700",),
                    issuer="TENCENT",
                    published_at=published,
                    title="Board Meeting Date",
                    document_type="hkex_announcement",
                    url="https://www1.hkexnews.hk/listedco/20260303001234.htm",
                    collected_at=published,
                    raw_metadata={
                        "news_id": "20260303001234",
                        "provider": "hkexnews",
                    },
                    market="hk",
                    effective_at=published,
                ),
                InformationItem(
                    source="hkexnews",
                    source_type="regulatory_filing",
                    external_id="20260303001234",
                    tickers=("00700",),
                    issuer="TENCENT",
                    published_at=published,
                    title="Board Meeting Date",
                    document_type="hkex_announcement",
                    url="https://www1.hkexnews.hk/listedco/20260303001234.htm",
                    collected_at=published,
                    raw_metadata={
                        "news_id": "20260303001234",
                        "provider": "hkexnews",
                    },
                    market="hk",
                    effective_at=published,
                ),
            ])

            raw = repository.query_feed(FeedFilters())
            display = repository.query_feed_display(FeedFilters())

            self.assertEqual(raw.total, 2)
            self.assertEqual(len(display.items), 2)
            self.assertEqual(
                display.items[0]["also_seen_on"],
                ["hkexnews"],
            )


if __name__ == "__main__":
    unittest.main()
