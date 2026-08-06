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
    rcept_no: str = None,
    title: str = "공시 제목",
    ticker: str = "005930",
    market: str = "kr",
    source_type: str = "regulatory_filing",
    published: datetime = None,
) -> dict:
    published = published or datetime(2026, 8, 5, 6, 40, tzinfo=timezone.utc)
    metadata = {}
    if rcept_no:
        metadata["rcept_no"] = rcept_no
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


def info_item(
    source: str,
    external_id: str,
    *,
    rcept_no: str,
    title: str = "공시 제목",
) -> InformationItem:
    published = datetime(2026, 8, 5, 6, 40, tzinfo=timezone.utc)
    return InformationItem(
        source=source,
        source_type="regulatory_filing",
        external_id=external_id,
        tickers=("005930",),
        issuer="삼성전자",
        published_at=published,
        title=title,
        document_type="dart_report",
        url="https://example.test/" + external_id,
        collected_at=datetime(2026, 8, 5, 7, tzinfo=timezone.utc),
        raw_metadata={"rcept_no": rcept_no},
        market="kr",
        effective_at=published,
    )


class DedupeKeyTests(unittest.TestCase):
    def test_same_receipt_folds_across_dart_and_kind(self) -> None:
        dart = feed_item("dart", "20260805000501", rcept_no="20260805000501")
        kind = feed_item("kind", "kind-1", rcept_no="20260805000501")

        self.assertEqual(dedupe_key(dart), dedupe_key(kind))

    def test_kind_acpt_no_alias_matches_dart_receipt(self) -> None:
        dart = feed_item("dart", "20260805000501", rcept_no="20260805000501")
        kind = {
            **feed_item("kind", "kind-1"),
            "raw_metadata": {"acpt_no": "20260805000501"},
        }

        self.assertEqual(dedupe_key(dart), dedupe_key(kind))

    def test_different_receipts_are_not_folded(self) -> None:
        first = feed_item("dart", "20260805000501", rcept_no="20260805000501")
        second = feed_item("kind", "kind-1", rcept_no="20260805000502")

        self.assertNotEqual(dedupe_key(first), dedupe_key(second))

    def test_same_title_same_day_with_different_receipts_not_folded(self) -> None:
        first = feed_item(
            "dart",
            "20260805000501",
            rcept_no="20260805000501",
            title="임원ㆍ주요주주특정증권등소유상황보고서",
        )
        second = feed_item(
            "kind",
            "kind-1",
            rcept_no="20260805000502",
            title="임원ㆍ주요주주특정증권등소유상황보고서",
        )

        self.assertNotEqual(dedupe_key(first), dedupe_key(second))

    def test_title_fallback_only_when_no_receipt(self) -> None:
        without = feed_item("future-source", "x", rcept_no=None)
        self.assertIn("005930", dedupe_key(without))

    def test_news_folds_same_ticker_day_title(self) -> None:
        first = feed_item(
            "naver_news",
            "naver-1",
            source_type="news",
            title="삼성전자 뉴스",
        )
        second = feed_item(
            "news",
            "finnhub-1",
            source_type="news",
            title="삼성전자 뉴스",
        )

        self.assertEqual(dedupe_key(first), dedupe_key(second))

    def test_news_different_day_not_folded(self) -> None:
        first = feed_item(
            "naver_news",
            "naver-1",
            source_type="news",
            title="삼성전자 뉴스",
        )
        second = feed_item(
            "news",
            "finnhub-1",
            source_type="news",
            title="삼성전자 뉴스",
            published=datetime(2026, 8, 4, 6, 40, tzinfo=timezone.utc),
        )

        self.assertNotEqual(dedupe_key(first), dedupe_key(second))


class FoldFeedItemsTests(unittest.TestCase):
    def test_fold_picks_dart_primary_and_lists_also_from(self) -> None:
        kind = feed_item("kind", "kind-1", rcept_no="20260805000501")
        dart = feed_item("dart", "20260805000501", rcept_no="20260805000501")

        folded = fold_feed_items([kind, dart])

        self.assertEqual(len(folded), 1)
        self.assertEqual(folded[0]["source"], "dart")
        self.assertEqual(folded[0]["also_from"], ["kind"])
        self.assertEqual(folded[0]["also_from_labels"], ["KIND (KRX)"])
        self.assertEqual(folded[0]["dedupe_count"], 2)

    def test_fold_keeps_single_items(self) -> None:
        single = feed_item("dart", "20260805000501", rcept_no="20260805000501")
        sec = feed_item("sec", "sec-1", market="us")

        folded = fold_feed_items([single, sec])

        self.assertEqual(len(folded), 2)
        self.assertNotIn("also_from", folded[0])

    def test_fold_disabled_returns_every_row(self) -> None:
        kind = feed_item("kind", "kind-1", rcept_no="20260805000501")
        dart = feed_item("dart", "20260805000501", rcept_no="20260805000501")

        folded = fold_feed_items([kind, dart], enabled=False)

        self.assertEqual(len(folded), 2)


class WebRepositoryDedupeTests(unittest.TestCase):
    def test_display_folds_while_raw_query_keeps_rows(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            database_path = Path(temporary_directory) / "web.sqlite3"
            items = SQLiteInformationRepository(database_path)
            repository = WebRepository(
                database_path,
                allowed_sources=("dart", "kind"),
                known_sources=(
                    SourceConfig("dart", "OpenDART", "filings", True),
                    SourceConfig("kind", "KIND (KRX)", "filings", True),
                ),
                implemented_sources=("dart", "kind"),
            )
            repository.add_companies_batch(
                "005930",
                ("holdings",),
                None,
                market="kr",
                name_fallback={"005930": {"name": "삼성전자", "exchange": "KRX"}},
            )
            items.save([
                info_item("dart", "20260805000501", rcept_no="20260805000501"),
                info_item("kind", "kind-1", rcept_no="20260805000501"),
            ])

            raw = repository.query_feed(FeedFilters())
            display = repository.query_feed_display(FeedFilters())

            self.assertEqual(raw.total, 2)
            self.assertEqual(len(display.items), 1)
            self.assertEqual(display.items[0]["source"], "dart")
            self.assertEqual(display.items[0]["also_from"], ["kind"])

            with patch.dict(
                os_environ(),
                {"KR_FEED_SOFT_DEDUPE": "false"},
                clear=False,
            ):
                display_disabled = repository.query_feed_display(FeedFilters())

            self.assertEqual(len(display_disabled.items), 2)


def os_environ():
    import os

    return os.environ


if __name__ == "__main__":
    unittest.main()
