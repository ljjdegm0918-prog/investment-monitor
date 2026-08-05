from datetime import date, datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest

from investment_monitor.config import SourceConfig
from investment_monitor.models import InformationItem
from investment_monitor.sqlite_repository import SQLiteInformationRepository
from investment_monitor.web_repository import FeedFilters, WebRepository


class FakeResolver:
    def resolve(self, ticker: str):
        records = {
            "AAPL": {
                "ticker": "AAPL",
                "name": "Apple Inc.",
                "exchange": "Nasdaq",
                "cik": "0000320193",
                "mapping_status": "mapped",
            },
            "MSFT": {
                "ticker": "MSFT",
                "name": "Microsoft Corporation",
                "exchange": "Nasdaq",
                "cik": "0000789019",
                "mapping_status": "mapped",
            },
        }
        return records.get(ticker)


def make_item(
    external_id: str,
    *,
    ticker: str = "AAPL",
    form: str = "10-Q",
    accepted_at: str = "2026-08-02T12:45:00+00:00",
    source: str = "sec",
    source_type: str = "",
    generated: bool = False,
) -> InformationItem:
    return InformationItem(
        source=source,
        source_type=source_type or ("regulatory_filing" if source == "sec" else "community"),
        external_id=external_id,
        tickers=(ticker,),
        issuer="Apple Inc." if ticker == "AAPL" else "Microsoft Corporation",
        published_at=datetime(2026, 8, 2, tzinfo=timezone.utc),
        title=f"{form} filing for {ticker}",
        document_type=form,
        url=f"https://www.sec.gov/Archives/{external_id}.htm",
        collected_at=datetime(2026, 8, 2, 13, tzinfo=timezone.utc),
        raw_metadata={
            "acceptanceDateTime": accepted_at,
            "generated": generated,
            "cik": "0000320193" if ticker == "AAPL" else "0000789019",
        },
    )


class WebRepositoryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = TemporaryDirectory()
        self.database_path = Path(self.temporary_directory.name) / "web.sqlite3"
        self.items = SQLiteInformationRepository(self.database_path)
        self.repository = WebRepository(self.database_path)
        self.resolver = FakeResolver()

    def tearDown(self) -> None:
        self.temporary_directory.cleanup()

    def add_company(self, ticker: str, *lists: str) -> None:
        result = self.repository.add_companies_batch(
            ticker, lists, self.resolver  # type: ignore[arg-type]
        )
        self.assertFalse(result["failed"])

    def test_fixed_lists_and_many_to_many_memberships_are_idempotent(self) -> None:
        self.add_company("aapl", "holdings", "watchlist")
        repeated = self.repository.add_companies_batch(
            "AAPL", ("holdings", "watchlist"), self.resolver  # type: ignore[arg-type]
        )

        company = self.repository.companies()[0]
        self.assertEqual(company["list_slugs"], ["holdings", "watchlist"])
        self.assertEqual(len(repeated["already_present"]), 1)
        self.assertEqual(
            [record["slug"] for record in self.repository.fixed_lists()],
            ["holdings", "planned", "watchlist"],
        )
        original_count = self.items.count()
        WebRepository(self.database_path)
        self.assertEqual(self.items.count(), original_count)

    def test_batch_add_allows_partial_success_and_normalizes_input(self) -> None:
        result = self.repository.add_companies_batch(
            "aapl, BAD\nmsft aapl", ("planned",), self.resolver  # type: ignore[arg-type]
        )

        self.assertEqual([record["ticker"] for record in result["added"]], ["AAPL", "MSFT"])
        self.assertEqual(result["failed"][0]["ticker"], "BAD")
        self.assertEqual([company["ticker"] for company in self.repository.companies()], ["AAPL", "MSFT"])

    def test_removing_memberships_preserves_other_lists_and_history(self) -> None:
        self.add_company("AAPL", "holdings", "watchlist")
        self.items.save([make_item("0000320193-26-000001")])

        self.assertTrue(self.repository.remove_membership("AAPL", "holdings"))
        self.assertEqual(self.repository.companies()[0]["list_slugs"], ["watchlist"])
        self.assertEqual(self.repository.query_feed(FeedFilters()).total, 1)

        self.assertEqual(self.repository.remove_all_memberships("AAPL"), 1)
        self.assertEqual(self.items.count(), 1)
        self.assertEqual(self.repository.companies()[0]["list_slugs"], [])
        self.assertEqual(self.repository.query_feed(FeedFilters()).total, 0)
        self.assertEqual(self.repository.active_tickers(), ())

    def test_active_tickers_are_the_database_source_of_truth(self) -> None:
        self.add_company("AAPL", "holdings", "watchlist")
        self.add_company("MSFT", "planned")

        self.assertEqual(self.repository.active_tickers(), ("AAPL", "MSFT"))

        self.repository.remove_membership("AAPL", "holdings")
        self.assertEqual(self.repository.active_tickers(), ("AAPL", "MSFT"))

        self.repository.remove_membership("AAPL", "watchlist")
        self.assertEqual(self.repository.active_tickers(), ("MSFT",))

    def test_active_tickers_without_sec_items_are_selected_for_backfill(self) -> None:
        self.add_company("AAPL", "holdings")
        self.add_company("MSFT", "watchlist")
        self.items.save([make_item("apple-existing")])

        self.assertEqual(
            self.repository.active_tickers_without_source_items("sec"),
            ("MSFT",),
        )

    def test_today_deduplicates_across_lists_and_uses_eastern_boundaries(self) -> None:
        self.add_company("AAPL", "holdings", "planned", "watchlist")
        self.items.save([
            make_item("same-item", accepted_at="2026-08-02T04:15:00+00:00"),
            make_item("previous-et-day", accepted_at="2026-08-02T03:59:59+00:00"),
        ])

        result = self.repository.query_feed(FeedFilters(
            start_date=date(2026, 8, 2), end_date=date(2026, 8, 2)
        ))

        self.assertEqual(result.total, 1)
        self.assertEqual(result.items[0]["external_id"], "same-item")
        self.assertEqual(result.items[0]["list_slugs"], ["holdings", "planned", "watchlist"])

        holdings_result = self.repository.query_feed(FeedFilters(list_slug="holdings"))
        self.assertEqual(
            holdings_result.items[0]["list_slugs"],
            ["holdings", "planned", "watchlist"],
        )

    def test_eastern_grouping_handles_offsets_and_daylight_saving_days(self) -> None:
        self.add_company("AAPL", "holdings")
        self.items.save([
            make_item("spring-before", accepted_at="2026-03-08T04:59:59Z"),
            make_item("spring-start", accepted_at="2026-03-08T00:00:00-05:00"),
            make_item("spring-end", accepted_at="2026-03-09T00:00:00-04:00"),
            make_item("fall-start", accepted_at="2026-11-01T00:00:00-04:00"),
            make_item("fall-late", accepted_at="2026-11-01T23:59:59-05:00"),
            make_item("fall-after", accepted_at="2026-11-02T05:00:00Z"),
        ])

        spring = self.repository.query_feed(FeedFilters(
            start_date=date(2026, 3, 8), end_date=date(2026, 3, 8)
        ))
        fall = self.repository.query_feed(FeedFilters(
            start_date=date(2026, 11, 1), end_date=date(2026, 11, 1)
        ))

        self.assertEqual({item["external_id"] for item in spring.items}, {"spring-start"})
        self.assertEqual({item["external_id"] for item in fall.items}, {"fall-start", "fall-late"})

    def test_read_state_persists_and_bulk_action_respects_active_scope(self) -> None:
        self.add_company("AAPL", "holdings")
        self.add_company("MSFT", "watchlist")
        self.items.save([
            make_item("apple-1"),
            make_item("apple-2", form="8-K"),
            make_item("microsoft-1", ticker="MSFT"),
        ])
        apple_scope = FeedFilters(list_slug="holdings")

        self.assertTrue(all(not item["is_read"] for item in self.repository.query_feed(apple_scope).items))
        self.assertEqual(self.repository.bulk_set_read(apple_scope, True), 2)
        reopened = WebRepository(self.database_path)
        self.assertTrue(all(item["is_read"] for item in reopened.query_feed(apple_scope).items))
        self.assertFalse(reopened.query_feed(FeedFilters(list_slug="watchlist")).items[0]["is_read"])
        self.assertEqual(reopened.counts(date(2026, 8, 2))["list_unread"]["holdings"], 0)
        apple_id = int(reopened.query_feed(apple_scope).items[0]["id"])
        self.assertEqual(reopened.set_read((apple_id,), False), 1)
        self.assertFalse(WebRepository(self.database_path).query_feed(apple_scope).items[0]["is_read"])
        self.assertEqual(WebRepository(self.database_path).counts(date(2026, 8, 2))["list_unread"]["holdings"], 1)

    def test_bulk_read_respects_combined_list_form_date_and_amendment_scope(self) -> None:
        self.add_company("AAPL", "holdings")
        self.add_company("MSFT", "watchlist")
        self.items.save([
            make_item("apple-original", form="10-Q", accepted_at="2026-08-02T12:00:00Z"),
            make_item("apple-amended", form="10-Q/A", accepted_at="2026-08-02T13:00:00Z"),
            make_item("apple-other-form", form="8-K", accepted_at="2026-08-02T14:00:00Z"),
            make_item("microsoft-original", ticker="MSFT", form="10-Q", accepted_at="2026-08-02T15:00:00Z"),
        ])
        exact_scope = FeedFilters(
            list_slug="holdings",
            form_type="10-Q",
            start_date=date(2026, 8, 2),
            end_date=date(2026, 8, 2),
            amendment="no",
        )

        self.assertEqual(self.repository.bulk_set_read(exact_scope, True), 1)
        all_items = {item["external_id"]: item for item in self.repository.query_feed(FeedFilters()).items}
        self.assertTrue(all_items["apple-original"]["is_read"])
        self.assertFalse(all_items["apple-amended"]["is_read"])
        self.assertFalse(all_items["apple-other-form"]["is_read"])
        self.assertFalse(all_items["microsoft-original"]["is_read"])

    def test_search_filters_and_stable_pagination(self) -> None:
        self.add_company("AAPL", "holdings")
        self.items.save([
            make_item("0003", form="8-K", accepted_at="2026-08-02T14:00:00+00:00"),
            make_item("0002", form="10-Q", accepted_at="2026-08-02T14:00:00+00:00"),
            make_item("0001", form="10-Q", accepted_at="2026-08-02T13:00:00+00:00"),
        ])

        search = self.repository.query_feed(FeedFilters(query="10-Q"))
        first_page = self.repository.query_feed(FeedFilters(page_size=2))
        second_page = self.repository.query_feed(FeedFilters(page=2, page_size=2))

        self.assertEqual(search.total, 2)
        self.assertEqual([item["external_id"] for item in first_page.items], ["0003", "0002"])
        self.assertEqual([item["external_id"] for item in second_page.items], ["0001"])

        combined = self.repository.query_feed(FeedFilters(
            list_slug="holdings",
            query="10-Q",
            form_type="10-Q",
            start_date=date(2026, 8, 2),
            end_date=date(2026, 8, 2),
            read_state="unread",
            amendment="no",
        ))
        beyond_last = self.repository.query_feed(FeedFilters(page=999, page_size=2))
        self.assertEqual(combined.total, 2)
        self.assertEqual(beyond_last.page, 2)
        self.assertEqual([item["external_id"] for item in beyond_last.items], ["0001"])

    def test_accession_deduplication_and_amendments_remain_separate(self) -> None:
        self.add_company("AAPL", "holdings")
        original = make_item("0000320193-26-000010", form="10-Q")
        amendment = make_item("0000320193-26-000011", form="10-Q/A")

        first = self.items.save([original, amendment])
        repeated = self.items.save([original, amendment])
        result = self.repository.query_feed(FeedFilters())

        self.assertEqual(first.inserted, 2)
        self.assertEqual(repeated.inserted, 0)
        self.assertEqual(repeated.updated, 2)
        self.assertEqual(result.total, 2)
        self.assertEqual({item["external_id"] for item in result.items}, {original.external_id, amendment.external_id})
        self.assertEqual(sum(bool(item["is_amendment"]) for item in result.items), 1)

    def test_production_feed_excludes_generated_and_unapproved_sources(self) -> None:
        self.add_company("AAPL", "holdings")
        self.items.save([
            make_item("live-sec"),
            make_item("demo-community", source="mock_community", generated=True),
        ])

        result = self.repository.query_feed(FeedFilters())

        self.assertEqual(result.total, 1)
        self.assertEqual(result.items[0]["source"], "sec")
        self.assertEqual(self.repository.query_feed(FeedFilters(information_type="community")).total, 0)

    def test_real_enabled_community_source_uses_shared_feed(self) -> None:
        self.add_company("AAPL", "holdings")
        self.items.save([make_item("reddit-1", source="reddit", generated=False)])
        production = WebRepository(self.database_path, allowed_sources=("sec", "reddit"))

        result = production.query_feed(FeedFilters(information_type="community"))
        statuses = {
            record["type"]: record
            for record in production.source_statuses(
                now=datetime(2026, 8, 2, 14, tzinfo=timezone.utc)
            )
        }

        self.assertEqual(result.total, 1)
        self.assertEqual(result.items[0]["source"], "reddit")
        self.assertEqual(statuses["Community"]["status"], "connected")

    def test_sec_source_status_distinguishes_stale_data(self) -> None:
        self.add_company("AAPL", "holdings")
        self.items.save([make_item("stale-sec-item")])

        statuses = self.repository.source_statuses(
            now=datetime(2026, 8, 5, 2, tzinfo=timezone.utc)
        )

        sec = next(record for record in statuses if record["type"] == "Filings")
        self.assertEqual(sec["status"], "stale")
        self.assertTrue(sec["is_stale"])

    def test_filings_status_is_driven_by_regulatory_filing_items(self) -> None:
        self.add_company("AAPL", "holdings")
        self.items.save([
            make_item("fresh-sec-item", accepted_at="2026-08-04T12:00:00+00:00")
        ])

        statuses = self.repository.source_statuses(
            now=datetime(2026, 8, 2, 14, tzinfo=timezone.utc)
        )

        filings = next(
            record for record in statuses if record["type"] == "Filings"
        )
        self.assertEqual(filings["status"], "connected")
        self.assertEqual(filings["provider"], "SEC EDGAR")

    def test_filings_status_can_be_driven_by_dart_items(self) -> None:
        repository = WebRepository(
            self.database_path,
            allowed_sources=("dart",),
            known_sources=(
                SourceConfig(
                    name="dart",
                    label="OpenDART",
                    source_type="filings",
                    enabled=True,
                ),
            ),
            implemented_sources=("dart",),
        )
        self.items.save([
            make_item(
                "dart-1",
                source="dart",
                source_type="regulatory_filing",
                accepted_at="2026-08-04T12:00:00+00:00",
            )
        ])

        statuses = repository.source_statuses(
            now=datetime(2026, 8, 2, 14, tzinfo=timezone.utc)
        )

        filings = next(
            record for record in statuses if record["type"] == "Filings"
        )
        self.assertEqual(filings["status"], "connected")
        self.assertEqual(filings["provider"], "OpenDART")

    def test_filings_status_combines_sec_and_dart_providers(self) -> None:
        repository = WebRepository(
            self.database_path,
            allowed_sources=("sec", "dart"),
            known_sources=(
                SourceConfig(
                    name="sec",
                    label="SEC EDGAR",
                    source_type="filings",
                    enabled=True,
                ),
                SourceConfig(
                    name="dart",
                    label="OpenDART",
                    source_type="filings",
                    enabled=True,
                ),
            ),
            implemented_sources=("sec", "dart"),
        )
        self.items.save([
            make_item("sec-1", accepted_at="2026-08-04T12:00:00+00:00"),
            make_item(
                "dart-1",
                source="dart",
                source_type="regulatory_filing",
                accepted_at="2026-08-04T12:30:00+00:00",
            ),
        ])

        statuses = repository.source_statuses(
            now=datetime(2026, 8, 2, 14, tzinfo=timezone.utc)
        )

        filings = next(
            record for record in statuses if record["type"] == "Filings"
        )
        self.assertEqual(filings["status"], "connected")
        self.assertEqual(filings["provider"], "SEC EDGAR, OpenDART")

    def test_filings_status_can_be_driven_by_kind_items(self) -> None:
        repository = WebRepository(
            self.database_path,
            allowed_sources=("kind",),
            known_sources=(
                SourceConfig(
                    name="kind",
                    label="KIND (KRX)",
                    source_type="filings",
                    enabled=True,
                ),
            ),
            implemented_sources=("kind",),
        )
        self.items.save([
            make_item(
                "kind-1",
                source="kind",
                source_type="regulatory_filing",
                accepted_at="2026-08-04T12:00:00+00:00",
            )
        ])

        statuses = repository.source_statuses(
            now=datetime(2026, 8, 2, 14, tzinfo=timezone.utc)
        )

        filings = next(
            record for record in statuses if record["type"] == "Filings"
        )
        self.assertEqual(filings["status"], "connected")
        self.assertEqual(filings["provider"], "KIND (KRX)")

    def test_filings_status_combines_sec_dart_and_kind_providers(self) -> None:
        repository = WebRepository(
            self.database_path,
            allowed_sources=("sec", "dart", "kind"),
            known_sources=(
                SourceConfig(
                    name="sec",
                    label="SEC EDGAR",
                    source_type="filings",
                    enabled=True,
                ),
                SourceConfig(
                    name="dart",
                    label="OpenDART",
                    source_type="filings",
                    enabled=True,
                ),
                SourceConfig(
                    name="kind",
                    label="KIND (KRX)",
                    source_type="filings",
                    enabled=True,
                ),
            ),
            implemented_sources=("sec", "dart", "kind"),
        )
        self.items.save([
            make_item("kind-1", source="kind", source_type="regulatory_filing")
        ])

        statuses = repository.source_statuses(
            now=datetime(2026, 8, 2, 14, tzinfo=timezone.utc)
        )

        filings = next(
            record for record in statuses if record["type"] == "Filings"
        )
        self.assertEqual(filings["status"], "connected")
        self.assertEqual(
            filings["provider"],
            "SEC EDGAR, OpenDART, KIND (KRX)",
        )

    def test_collection_activity_is_persisted_without_invented_metrics(self) -> None:
        started = datetime(2026, 8, 2, 12, tzinfo=timezone.utc)
        finished = datetime(2026, 8, 2, 12, 0, 2, tzinfo=timezone.utc)
        self.repository.record_collection_events((SimpleNamespace(
            source="sec",
            ticker="AAPL",
            started_at=started,
            finished_at=finished,
            status="success",
            records_read=3,
            records_written=2,
            duplicate_records=1,
            error_message=None,
        ),))

        activity = self.repository.activity(source="sec", status="success")

        self.assertEqual(len(activity["runs"]), 1)
        self.assertEqual(len(activity["logs"]), 1)
        self.assertEqual(activity["runs"][0]["records_fetched"], 3)
        self.assertEqual(activity["runs"][0]["records_inserted"], 2)
        self.assertEqual(activity["runs"][0]["duplicate_records"], 1)
        self.assertEqual(
            self.repository.activity(
                source="sec",
                status="success",
                start_date=date(2026, 8, 2),
                end_date=date(2026, 8, 2),
            )["logs"][0]["records_written"],
            2,
        )
        self.assertEqual(
            self.repository.activity(start_date=date(2026, 8, 3))["logs"],
            [],
        )

    def test_secret_settings_are_whitelisted_and_masked(self) -> None:
        repository = WebRepository(
            self.database_path,
            allowed_secret_keys=("FINNHUB_API_KEY", "SEC_USER_AGENT"),
        )
        repository.set_setting(
            "FINNHUB_API_KEY",
            "  sk-finnhub-12345678  ",
        )

        status = repository.setting_status(("FINNHUB_API_KEY",))[
            "FINNHUB_API_KEY"
        ]
        loaded = repository.load_setting_values(("FINNHUB_API_KEY",))

        self.assertTrue(status["configured"])
        self.assertNotIn("sk-finnhub-12345678", status["hint"])
        self.assertEqual(status["hint"], "••••5678")
        self.assertEqual(loaded["FINNHUB_API_KEY"], "sk-finnhub-12345678")
        self.assertEqual(
            repository.setting_status(("SEC_USER_AGENT",))["SEC_USER_AGENT"],
            {"configured": False, "hint": ""},
        )

    def test_clearing_secret_setting_removes_it(self) -> None:
        repository = WebRepository(
            self.database_path,
            allowed_secret_keys=("FINNHUB_API_KEY",),
        )
        repository.set_setting("FINNHUB_API_KEY", "secret-value")
        repository.set_setting("FINNHUB_API_KEY", "   ")

        status = repository.setting_status(("FINNHUB_API_KEY",))[
            "FINNHUB_API_KEY"
        ]

        self.assertFalse(status["configured"])
        self.assertEqual(status["hint"], "")
        self.assertNotIn(
            "FINNHUB_API_KEY",
            repository.load_setting_values(("FINNHUB_API_KEY",)),
        )

    def test_arbitrary_setting_key_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            self.repository.set_setting("AWS_SECRET_ACCESS_KEY", "x")

    def test_extra_env_settings_are_validated_and_stored(self) -> None:
        self.repository.set_setting("extra_env:CUSTOM_VAR", "value-1")

        stored = self.repository.load_extra_env()
        status = self.repository.setting_status(("extra_env:CUSTOM_VAR",))[
            "extra_env:CUSTOM_VAR"
        ]

        self.assertEqual(stored, (("CUSTOM_VAR", "value-1"),))
        self.assertTrue(status["configured"])
        self.assertEqual(status["hint"], "••••ue-1")

        self.repository.set_setting("extra_env:CUSTOM_VAR", "")
        self.assertEqual(self.repository.load_extra_env(), ())

    def test_extra_env_rejects_invalid_and_dangerous_names(self) -> None:
        for bad_name in (
            "1BAD",
            "HAS-DASH",
            "PATH",
            "PYTHONPATH",
            "HOME",
            "USERPROFILE",
            "TEMP",
            "LD_LIBRARY_PATH",
            "SSL_CERT_FILE",
            "PYTHONHOME",
        ):
            with self.assertRaises(ValueError, msg=bad_name):
                self.repository.set_setting(f"extra_env:{bad_name}", "x")

    def test_news_status_aggregates_multiple_news_sources(self) -> None:
        repository = WebRepository(
            self.database_path,
            allowed_sources=("news", "naver_news"),
            known_sources=(
                SourceConfig(
                    name="news",
                    label="News",
                    source_type="news",
                    enabled=True,
                ),
                SourceConfig(
                    name="naver_news",
                    label="Naver Finance",
                    source_type="news",
                    enabled=True,
                ),
            ),
            implemented_sources=("news", "naver_news"),
        )
        self.items.save([
            make_item("news-1", source="news", source_type="news"),
            make_item(
                "naver-1",
                source="naver_news",
                source_type="news",
            ),
        ])

        statuses = repository.source_statuses(
            now=datetime(2026, 8, 2, 14, tzinfo=timezone.utc)
        )

        news = next(
            record for record in statuses if record["type"] == "News"
        )
        self.assertEqual(news["status"], "connected")
        self.assertEqual(news["provider"], "Finnhub News, Naver Finance")


if __name__ == "__main__":
    unittest.main()
