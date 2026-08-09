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
    title: str = "Santander amplia su programa de recompra",
    ticker: str = "SAN",
    market: str = "es",
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


class EsDedupeKeyTests(unittest.TestCase):
    def test_es_market_key_is_non_empty_for_news(self) -> None:
        item = feed_item("yahoo_es", "y-1")

        self.assertIsNotNone(dedupe_key(item))

    def test_es_news_folds_across_sources_by_ticker_day_title(self) -> None:
        first = feed_item("yahoo_es", "y-1")
        second = feed_item("google_news_es", "g-1")

        self.assertEqual(dedupe_key(first), dedupe_key(second))
        self.assertTrue(dedupe_key(first).startswith("es-news:"))
        self.assertIn("SAN|2026-08-05|", dedupe_key(first))

    def test_es_news_different_day_does_not_fold(self) -> None:
        first = feed_item(
            "yahoo_es",
            "y-1",
            published=datetime(2026, 8, 5, 10, 0, tzinfo=timezone.utc),
        )
        second = feed_item(
            "google_news_es",
            "g-1",
            published=datetime(2026, 8, 6, 10, 0, tzinfo=timezone.utc),
        )

        self.assertNotEqual(dedupe_key(first), dedupe_key(second))

    def test_es_news_different_title_does_not_fold(self) -> None:
        first = feed_item(
            "yahoo_es", "y-1", title="Santander amplia su recompra"
        )
        second = feed_item(
            "google_news_es", "g-1", title="La bolsa espanola cierra al alza"
        )

        self.assertNotEqual(dedupe_key(first), dedupe_key(second))

    def test_es_news_different_ticker_does_not_fold(self) -> None:
        first = feed_item("yahoo_es", "y-1", ticker="SAN")
        second = feed_item("google_news_es", "g-1", ticker="TEF")

        self.assertNotEqual(dedupe_key(first), dedupe_key(second))

    def test_madrid_day_uses_spain_timezone(self) -> None:
        late_utc = feed_item(
            "yahoo_es",
            "y-1",
            published=datetime(2026, 8, 5, 23, 30, tzinfo=timezone.utc),
        )
        early_utc = feed_item(
            "google_news_es",
            "g-1",
            published=datetime(2026, 8, 5, 13, 0, tzinfo=timezone.utc),
        )

        # 23:30 UTC = 01:30 CEST next day; 13:00 UTC = 15:00 CEST same day.
        self.assertIn("2026-08-06", dedupe_key(late_utc))
        self.assertIn("2026-08-05", dedupe_key(early_utc))

    def test_cnmv_filing_same_document_id_pairs(self) -> None:
        first = feed_item(
            "cnmv_hr",
            "42373",
            source_type="regulatory_filing",
            raw_metadata={"document_id": "42373"},
        )
        second = feed_item(
            "cnmv_hr",
            "42373",
            source_type="regulatory_filing",
            raw_metadata={"document_id": "42373"},
        )

        self.assertEqual(dedupe_key(first), dedupe_key(second))
        self.assertTrue(dedupe_key(first).startswith("es:filing:cnmv:"))

    def test_bme_filing_same_document_id_pairs(self) -> None:
        first = feed_item(
            "bme_relevant_facts",
            "OI:42373",
            source_type="regulatory_filing",
            raw_metadata={"document_id": "OI:42373"},
        )
        second = feed_item(
            "bme_relevant_facts",
            "OI:42373",
            source_type="regulatory_filing",
            raw_metadata={"document_id": "OI:42373"},
        )

        self.assertEqual(dedupe_key(first), dedupe_key(second))
        self.assertTrue(dedupe_key(first).startswith("es:filing:bme:"))

    def test_cnmv_and_bme_never_pair_by_document_id(self) -> None:
        first = feed_item(
            "cnmv_hr",
            "42373",
            source_type="regulatory_filing",
            raw_metadata={"document_id": "42373"},
        )
        second = feed_item(
            "bme_relevant_facts",
            "OI:42373",
            source_type="regulatory_filing",
            raw_metadata={"document_id": "OI:42373"},
        )

        self.assertNotEqual(dedupe_key(first), dedupe_key(second))

    def test_es_filing_title_fallback_is_source_scoped(self) -> None:
        title = "Programas de recompra de acciones"
        first = feed_item(
            "cnmv_hr",
            "",
            source_type="regulatory_filing",
            title=title,
        )
        second = feed_item(
            "bme_relevant_facts",
            "",
            source_type="regulatory_filing",
            title=title,
        )

        self.assertTrue(
            dedupe_key(first).startswith("es:filing:title:cnmv_hr:")
        )
        self.assertNotEqual(dedupe_key(first), dedupe_key(second))

    def test_us_market_still_has_no_key(self) -> None:
        item = feed_item("sec", "sec-1", market="us")

        self.assertIsNone(dedupe_key(item))


class EsAnnotateTests(unittest.TestCase):
    def test_news_same_key_keeps_both_rows_annotated(self) -> None:
        first = feed_item("yahoo_es", "y-1")
        second = feed_item("google_news_es", "g-1")

        annotated = annotate_feed_items([first, second])

        self.assertEqual(len(annotated), 2)
        self.assertEqual(annotated[0]["also_seen_on"], ["google_news_es"])
        self.assertEqual(
            annotated[0]["also_seen_on_labels"],
            ["Google News (ES)"],
        )
        self.assertEqual(annotated[1]["also_seen_on"], ["yahoo_es"])
        self.assertEqual(
            annotated[1]["also_seen_on_labels"],
            ["Yahoo Finance ES"],
        )
        self.assertEqual(annotated[0]["dedupe_count"], 2)

    def test_switch_off_returns_all_rows_without_annotations(self) -> None:
        first = feed_item("yahoo_es", "y-1")
        second = feed_item("google_news_es", "g-1")

        annotated = annotate_feed_items([first, second], enabled=False)

        self.assertEqual(len(annotated), 2)
        self.assertNotIn("also_seen_on", annotated[0])
        self.assertNotIn("also_seen_on", annotated[1])

    def test_cross_source_news_different_title_is_not_annotated(self) -> None:
        first = feed_item("yahoo_es", "y-1", title="Santander amplia recompra")
        second = feed_item(
            "google_news_es", "g-1", title="La bolsa espanola cierra"
        )

        annotated = annotate_feed_items([first, second])

        self.assertEqual(len(annotated), 2)
        self.assertNotIn("also_seen_on", annotated[0])
        self.assertNotIn("also_seen_on", annotated[1])


class WebRepositoryEsDedupeTests(unittest.TestCase):
    def test_display_annotates_es_news_while_raw_keeps_rows(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            database_path = Path(temporary_directory) / "web.sqlite3"
            items = SQLiteInformationRepository(database_path)
            repository = WebRepository(
                database_path,
                allowed_sources=("yahoo_es", "google_news_es"),
                known_sources=(
                    SourceConfig(
                        "yahoo_es",
                        "Yahoo Finance ES",
                        "news",
                        True,
                    ),
                    SourceConfig(
                        "google_news_es",
                        "Google News (ES)",
                        "news",
                        True,
                    ),
                ),
                implemented_sources=("yahoo_es", "google_news_es"),
            )
            repository.add_companies_batch(
                "SAN",
                ("holdings",),
                None,
                market="es",
            )
            published = datetime(2026, 8, 5, 10, 0, tzinfo=timezone.utc)
            items.save([
                InformationItem(
                    source="yahoo_es",
                    source_type="news",
                    external_id="y-1",
                    tickers=("SAN",),
                    issuer="SAN",
                    published_at=published,
                    title="Santander amplia su programa de recompra",
                    document_type="news",
                    url="https://example.com/y",
                    collected_at=published,
                    raw_metadata={},
                    market="es",
                    effective_at=published,
                ),
                InformationItem(
                    source="google_news_es",
                    source_type="news",
                    external_id="g-1",
                    tickers=("SAN",),
                    issuer="SAN",
                    published_at=published,
                    title="Santander amplia su programa de recompra",
                    document_type="news",
                    url="https://example.com/g",
                    collected_at=published,
                    raw_metadata={},
                    market="es",
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
                {("Google News (ES)",), ("Yahoo Finance ES",)},
            )


if __name__ == "__main__":
    unittest.main()
