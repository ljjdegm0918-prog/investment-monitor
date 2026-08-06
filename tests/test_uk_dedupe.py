from datetime import date, datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from investment_monitor import (
    InformationItem,
    SQLiteInformationRepository,
    WebRepository,
)
from investment_monitor.config import SourceConfig
from investment_monitor.dedupe import dedupe_key, fold_feed_items
from investment_monitor.web_repository import FeedFilters


def feed_item(
    source: str,
    external_id: str,
    *,
    rns_id: str = None,
    title: str = "Announcement title",
    ticker: str = "VOD",
    market: str = "uk",
    source_type: str = "regulatory_filing",
    published: datetime = None,
) -> dict:
    published = published or datetime(
        2026, 8, 5, 10, 0, tzinfo=timezone.utc
    )
    metadata = {}
    if rns_id:
        metadata["rns_id"] = rns_id
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


class UkDedupeKeyTests(unittest.TestCase):
    def test_investegate_rns_id_is_a_stable_key(self) -> None:
        item = feed_item("investegate", "9707019", rns_id="9707019")

        self.assertEqual(dedupe_key(item), "uk:filing:rns:9707019")

    def test_different_rns_ids_do_not_fold(self) -> None:
        first = feed_item("investegate", "9707019", rns_id="9707019")
        second = feed_item("investegate", "9704388", rns_id="9704388")

        self.assertNotEqual(dedupe_key(first), dedupe_key(second))

    def test_companies_house_transaction_id_is_a_stable_key(self) -> None:
        first = feed_item(
            "companies_house",
            "MzUzNjA1OTI4NGFkaXF6a2N4",
        )
        second = feed_item(
            "companies_house",
            "MzUzNjA1OTI4NGFkaXF6a2N4",
        )
        investegate = feed_item("investegate", "9707019", rns_id="9707019")

        self.assertEqual(dedupe_key(first), dedupe_key(second))
        self.assertEqual(
            dedupe_key(first),
            "uk:filing:ch:MzUzNjA1OTI4NGFkaXF6a2N4",
        )
        self.assertNotEqual(dedupe_key(first), dedupe_key(investegate))

    def test_investegate_and_ch_same_title_never_cross_fold(self) -> None:
        title = "Appointment of a director"
        investegate = feed_item(
            "investegate",
            "not-a-rns-hash",
            title=title,
        )
        ch = feed_item(
            "companies_house",
            "MzUzNjA1OTI4NGFkaXF6a2N4",
            title=title,
        )

        self.assertNotEqual(dedupe_key(investegate), dedupe_key(ch))

    def test_same_source_title_fallback_folds(self) -> None:
        first = feed_item("investegate", "hash-a", title="Director Dealings")
        second = feed_item("investegate", "hash-b", title="Director Dealings")

        self.assertEqual(dedupe_key(first), dedupe_key(second))

    def test_london_day_uses_europe_london_timezone(self) -> None:
        late_utc = feed_item(
            "investegate",
            "hash-x",
            title="Director Dealings",
            published=datetime(2026, 8, 5, 23, 30, tzinfo=timezone.utc),
        )

        self.assertIn("2026-08-06", dedupe_key(late_utc))

    def test_uk_news_folds_by_ticker_day_title(self) -> None:
        first = feed_item(
            "yahoo_uk",
            "110000619",
            source_type="news",
            title="Vodafone news",
        )
        second = feed_item(
            "yahoo_uk",
            "110000620",
            source_type="news",
            title="VODAFONE NEWS",
        )

        self.assertEqual(dedupe_key(first), dedupe_key(second))
        self.assertIn("2026-08-05", dedupe_key(first))

    def test_us_market_still_has_no_key(self) -> None:
        item = feed_item("sec", "sec-1", market="us")

        self.assertIsNone(dedupe_key(item))

    def test_kr_receipt_behavior_is_unchanged(self) -> None:
        dart = feed_item(
            "dart",
            "20260805000501",
            market="kr",
            rns_id=None,
        )
        dart["raw_metadata"]["rcept_no"] = "20260805000501"
        kind = feed_item(
            "kind",
            "kind-1",
            market="kr",
        )
        kind["raw_metadata"]["acpt_no"] = "20260805000501"

        self.assertEqual(dedupe_key(dart), dedupe_key(kind))


class UkFoldFeedItemsTests(unittest.TestCase):
    def test_single_strong_id_item_stays_single(self) -> None:
        item = feed_item("investegate", "9707019", rns_id="9707019")

        folded = fold_feed_items([item])

        self.assertEqual(len(folded), 1)
        self.assertNotIn("also_from", folded[0])

    def test_same_source_title_fold_picks_primary_and_lists_also_from(
        self,
    ) -> None:
        first = feed_item("investegate", "hash-a", title="Director Dealings")
        second = feed_item("investegate", "hash-b", title="Director Dealings")

        folded = fold_feed_items([first, second])

        self.assertEqual(len(folded), 1)
        self.assertEqual(folded[0]["source"], "investegate")
        self.assertEqual(folded[0]["also_from"], ["investegate"])
        self.assertEqual(folded[0]["dedupe_count"], 2)

    def test_news_items_fold(self) -> None:
        first = feed_item(
            "yahoo_uk",
            "110000619",
            source_type="news",
            title="Vodafone news",
        )
        second = feed_item(
            "yahoo_uk",
            "110000620",
            source_type="news",
            title="Vodafone news",
        )

        folded = fold_feed_items([first, second])

        self.assertEqual(len(folded), 1)
        self.assertEqual(folded[0]["source"], "yahoo_uk")
        self.assertEqual(folded[0]["also_from"], ["yahoo_uk"])


class WebRepositoryUkDedupeTests(unittest.TestCase):
    def test_display_folds_uk_while_raw_keeps_rows(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            database_path = Path(temporary_directory) / "web.sqlite3"
            items = SQLiteInformationRepository(database_path)
            repository = WebRepository(
                database_path,
                allowed_sources=("investegate",),
                known_sources=(
                    SourceConfig("investegate", "Investegate", "filings", True),
                ),
                implemented_sources=("investegate",),
            )
            repository.add_companies_batch(
                "VOD",
                ("holdings",),
                None,
                market="uk",
            )
            published = datetime(2026, 8, 5, 10, 0, tzinfo=timezone.utc)
            items.save([
                InformationItem(
                    source="investegate",
                    source_type="regulatory_filing",
                    external_id="9707019",
                    tickers=("VOD",),
                    issuer="VOD",
                    published_at=published,
                    title="Director/PDMR Shareholding",
                    document_type="rns_announcement",
                    url="https://www.investegate.co.uk/announcement/9707019",
                    collected_at=published,
                    raw_metadata={"rns_id": "9707019", "provider": "investegate"},
                    market="uk",
                    effective_at=published,
                ),
                InformationItem(
                    source="investegate",
                    source_type="regulatory_filing",
                    external_id="9704388",
                    tickers=("VOD",),
                    issuer="VOD",
                    published_at=published,
                    title="Admission to Trading",
                    document_type="rns_announcement",
                    url="https://www.investegate.co.uk/announcement/9704388",
                    collected_at=published,
                    raw_metadata={"rns_id": "9704388", "provider": "investegate"},
                    market="uk",
                    effective_at=published,
                ),
            ])

            raw = repository.query_feed(FeedFilters())
            display = repository.query_feed_display(FeedFilters())

            self.assertEqual(raw.total, 2)
            self.assertEqual(len(display.items), 2)
            self.assertNotIn("also_from", display.items[0])


if __name__ == "__main__":
    unittest.main()
