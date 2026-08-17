from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from typing import Optional
import unittest

from investment_monitor.config import SourceConfig
from investment_monitor.models import InformationItem
from investment_monitor.pipeline import CollectionEvent
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


def make_sync_event(
    source: str,
    ticker: str,
    market: str,
    status: str,
    *,
    initial_backfill: bool,
    requested_start: date = date(2025, 8, 1),
    requested_end: date = date(2026, 8, 1),
    effective_start: date = date(2025, 8, 1),
    effective_end: date = date(2026, 8, 1),
    error: str = "",
    coverage_kind: str = "complete_window",
    started_at: Optional[datetime] = None,
    finished_at: Optional[datetime] = None,
) -> CollectionEvent:
    now = started_at or datetime(2026, 8, 1, 12, tzinfo=timezone.utc)
    return CollectionEvent(
        source=source,
        ticker=ticker,
        started_at=now,
        finished_at=finished_at or now,
        status=status,
        records_read=0,
        records_written=0,
        records_inserted=0,
        records_updated=0,
        duplicate_records=0,
        error_message=error or None,
        market=market,
        requested_start_date=requested_start,
        requested_end_date=requested_end,
        effective_start_date=effective_start,
        effective_end_date=effective_end,
        coverage_kind=coverage_kind,
        initial_backfill=initial_backfill,
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

    def test_dynamic_list_crud_and_deleted_default_does_not_reappear(self) -> None:
        created = self.repository.create_list("Long Term Quality")
        renamed = self.repository.rename_list(created["slug"], "Quality Compounders")
        self.add_company("AAPL", created["slug"])
        deleted = self.repository.delete_list(created["slug"])

        self.assertEqual(renamed["name"], "Quality Compounders")
        self.assertEqual(deleted["removed_memberships"], 1)
        self.assertNotIn(created["slug"], {
            record["slug"] for record in self.repository.fixed_lists()
        })

        self.repository.delete_list("watchlist")
        WebRepository(self.database_path)
        self.assertNotIn("watchlist", {
            record["slug"] for record in self.repository.fixed_lists()
        })

    def test_connector_statuses_report_new_market_regions(self) -> None:
        expected = {
            "eqs_dgap": "Germany",
            "yahoo_de": "Germany",
            "google_news_de": "Germany",
            "eqs_nl": "Netherlands",
            "yahoo_nl": "Netherlands",
            "google_news_nl": "Netherlands",
            "eqs_it": "Italy",
            "yahoo_it": "Italy",
            "google_news_it": "Italy",
            "cnmv_hr": "Spain",
            "bme_relevant_facts": "Spain",
            "yahoo_es": "Spain",
            "google_news_es": "Spain",
            "sgx_announcements": "Singapore",
            "yahoo_sg": "Singapore",
            "google_news_sg": "Singapore",
            "fsma_stori": "Belgium",
            "be_second_disclosure": "Belgium",
            "yahoo_be": "Belgium",
            "google_news_be": "Belgium",
            "eqs_ch": "Switzerland",
            "six_official_notices": "Switzerland",
            "yahoo_ch": "Switzerland",
            "google_news_ch": "Switzerland",
            "gpw_espi": "Poland",
            "yahoo_pl": "Poland",
            "google_news_pl": "Poland",
            "fi_oam": "Sweden",
            "yahoo_se": "Sweden",
            "google_news_se": "Sweden",
        }
        sources = tuple(
            SourceConfig(
                name=name,
                label=name,
                source_type="filings" if name in {
                    "eqs_dgap", "eqs_nl", "eqs_it", "cnmv_hr",
                    "bme_relevant_facts", "sgx_announcements", "fsma_stori",
                    "be_second_disclosure", "eqs_ch", "six_official_notices",
                    "gpw_espi", "fi_oam",
                } else "news",
                enabled=True,
            )
            for name in expected
        )
        repository = WebRepository(
            self.database_path,
            allowed_sources=tuple(expected),
            known_sources=sources,
            implemented_sources=tuple(expected),
        )

        statuses = {
            record["name"]: record
            for record in repository.connector_statuses()
        }

        self.assertTrue(set(expected).issubset(statuses))
        for name, region in expected.items():
            with self.subTest(source=name):
                self.assertEqual(statuses[name]["regions"], [region])

    def test_stub_sources_with_empty_runs_never_report_connected(self) -> None:
        stub_names = (
            "maya_announcements",
            "bmv_relevant_events",
            "bse_hu_announcements",
            "wiener_boerse_news",
            "newsweb_no",
            "euronext_lisbon_news",
        )
        sources = tuple(
            SourceConfig(name=name, label=name, source_type="filings", enabled=True)
            for name in stub_names
        )
        repository = WebRepository(
            self.database_path,
            allowed_sources=stub_names,
            known_sources=sources,
            implemented_sources=stub_names,
        )
        now = datetime(2026, 8, 1, 12, tzinfo=timezone.utc)
        repository.record_collection_events(tuple(
            make_sync_event(name, "CANARY", "unknown", "empty", initial_backfill=False)
            for name in stub_names
        ))

        statuses = {
            record["name"]: record
            for record in repository.connector_statuses(now=now)
        }
        for name in stub_names:
            with self.subTest(source=name):
                self.assertEqual(statuses[name]["status"], "stub")
                self.assertIsNone(statuses[name]["latest_success"])

        filings = next(
            record
            for record in repository.source_statuses(now=now)
            if record["type"] == "Filings"
        )
        self.assertEqual(filings["status"], "stub")

    def test_stub_empty_run_does_not_lift_filings_for_real_source(self) -> None:
        sources = (
            SourceConfig(name="sec", label="SEC EDGAR", source_type="filings", enabled=True),
            SourceConfig(
                name="maya_announcements",
                label="MAYA (TASE)",
                source_type="filings",
                enabled=True,
            ),
        )
        repository = WebRepository(
            self.database_path,
            allowed_sources=("sec", "maya_announcements"),
            known_sources=sources,
            implemented_sources=("sec", "maya_announcements"),
        )
        now = datetime(2026, 8, 1, 12, tzinfo=timezone.utc)
        repository.record_collection_events((
            make_sync_event(
                "maya_announcements",
                "CANARY",
                "il",
                "empty",
                initial_backfill=False,
            ),
        ))

        statuses = {
            record["name"]: record
            for record in repository.connector_statuses(now=now)
        }
        self.assertEqual(statuses["maya_announcements"]["status"], "stub")
        filings = next(
            record
            for record in repository.source_statuses(now=now)
            if record["type"] == "Filings"
        )
        self.assertEqual(filings["status"], "unavailable")

    def test_real_source_empty_run_counts_as_connected(self) -> None:
        now = datetime(2026, 8, 1, 12, tzinfo=timezone.utc)
        self.repository.record_collection_events((
            make_sync_event(
                "sec",
                "AAPL",
                "us",
                "empty",
                initial_backfill=False,
            ),
        ))

        statuses = {
            record["name"]: record
            for record in self.repository.connector_statuses(now=now)
        }
        self.assertEqual(statuses["sec"]["status"], "connected")
        self.assertIsNotNone(statuses["sec"]["latest_success"])
        filings = next(
            record
            for record in self.repository.source_statuses(now=now)
            if record["type"] == "Filings"
        )
        self.assertEqual(filings["status"], "connected")

    def test_stub_failure_does_not_mask_real_source_filings_status(self) -> None:
        sources = (
            SourceConfig(name="sec", label="SEC EDGAR", source_type="filings", enabled=True),
            SourceConfig(
                name="maya_announcements",
                label="MAYA (TASE)",
                source_type="filings",
                enabled=True,
            ),
        )
        repository = WebRepository(
            self.database_path,
            allowed_sources=("sec", "maya_announcements"),
            known_sources=sources,
            implemented_sources=("sec", "maya_announcements"),
        )
        now = datetime(2026, 8, 1, 13, tzinfo=timezone.utc)
        repository.record_collection_events((
            make_sync_event(
                "sec",
                "AAPL",
                "us",
                "success",
                initial_backfill=False,
                started_at=datetime(2026, 8, 1, 10, tzinfo=timezone.utc),
            ),
            make_sync_event(
                "maya_announcements",
                "CANARY",
                "il",
                "failure",
                initial_backfill=False,
                error="stub reported failure",
                started_at=datetime(2026, 8, 1, 11, tzinfo=timezone.utc),
            ),
        ))

        statuses = {
            record["name"]: record
            for record in repository.connector_statuses(now=now)
        }
        self.assertEqual(statuses["sec"]["status"], "connected")
        self.assertEqual(statuses["maya_announcements"]["status"], "stub")
        filings = next(
            record
            for record in repository.source_statuses(now=now)
            if record["type"] == "Filings"
        )
        self.assertEqual(filings["status"], "connected")

    def test_stub_empty_does_not_mask_real_source_failure(self) -> None:
        sources = (
            SourceConfig(name="sec", label="SEC EDGAR", source_type="filings", enabled=True),
            SourceConfig(
                name="maya_announcements",
                label="MAYA (TASE)",
                source_type="filings",
                enabled=True,
            ),
        )
        repository = WebRepository(
            self.database_path,
            allowed_sources=("sec", "maya_announcements"),
            known_sources=sources,
            implemented_sources=("sec", "maya_announcements"),
        )
        repository.record_collection_events((
            make_sync_event(
                "sec",
                "AAPL",
                "us",
                "success",
                initial_backfill=False,
                started_at=datetime(2026, 8, 1, 9, tzinfo=timezone.utc),
            ),
        ))
        repository.record_collection_events((
            make_sync_event(
                "sec",
                "AAPL",
                "us",
                "failure",
                initial_backfill=False,
                error="edgar throttled",
                started_at=datetime(2026, 8, 1, 10, tzinfo=timezone.utc),
            ),
            make_sync_event(
                "maya_announcements",
                "CANARY",
                "il",
                "empty",
                initial_backfill=False,
                started_at=datetime(2026, 8, 1, 11, tzinfo=timezone.utc),
            ),
        ))
        now = datetime(2026, 8, 1, 13, tzinfo=timezone.utc)

        statuses = {
            record["name"]: record
            for record in repository.connector_statuses(now=now)
        }
        self.assertEqual(statuses["sec"]["status"], "temporarily_unavailable")
        self.assertEqual(statuses["maya_announcements"]["status"], "stub")
        filings = next(
            record
            for record in repository.source_statuses(now=now)
            if record["type"] == "Filings"
        )
        self.assertEqual(filings["status"], "temporarily_unavailable")

    def test_stub_only_failure_run_stays_stub(self) -> None:
        stub_names = ("maya_announcements",)
        sources = (
            SourceConfig(
                name="maya_announcements",
                label="MAYA (TASE)",
                source_type="filings",
                enabled=True,
            ),
        )
        repository = WebRepository(
            self.database_path,
            allowed_sources=stub_names,
            known_sources=sources,
            implemented_sources=stub_names,
        )
        now = datetime(2026, 8, 1, 13, tzinfo=timezone.utc)
        repository.record_collection_events((
            make_sync_event(
                "maya_announcements",
                "CANARY",
                "il",
                "failure",
                initial_backfill=False,
                error="stub reported failure",
            ),
        ))

        statuses = {
            record["name"]: record
            for record in repository.connector_statuses(now=now)
        }
        self.assertEqual(statuses["maya_announcements"]["status"], "stub")
        filings = next(
            record
            for record in repository.source_statuses(now=now)
            if record["type"] == "Filings"
        )
        self.assertEqual(filings["status"], "stub")

    def test_sync_state_is_independent_per_source_ticker_and_market(self) -> None:
        repository = WebRepository(
            self.database_path,
            allowed_sources=("sec", "news", "cnmv_hr", "bme_relevant_facts"),
        )
        repository.add_companies_batch(
            "AAPL", ("holdings",), self.resolver, market="us"
        )
        repository.add_companies_batch(
            "SAN", ("holdings",), None, market="es"
        )
        repository.ensure_source_ticker_sync_states((
            ("sec", "AAPL", "us"),
            ("news", "AAPL", "us"),
            ("cnmv_hr", "SAN", "es"),
            ("bme_relevant_facts", "SAN", "es"),
        ))
        self.items.save((
            make_item(
                "aapl-news-existing",
                source="news",
                source_type="news",
            ),
            InformationItem(
                source="cnmv_hr",
                source_type="regulatory_filing",
                external_id="42390",
                tickers=("SAN",),
                issuer="BANCO SANTANDER, S.A.",
                published_at=datetime(2026, 8, 1, tzinfo=timezone.utc),
                title="Santander disclosure",
                document_type="hecho_relevante",
                url="https://example.test/cnmv/42390",
                collected_at=datetime(2026, 8, 1, tzinfo=timezone.utc),
                raw_metadata={},
                market="es",
            ),
        ))
        repository.record_collection_events((
            make_sync_event("news", "AAPL", "us", "success", initial_backfill=True),
            make_sync_event(
                "cnmv_hr",
                "SAN",
                "es",
                "success",
                initial_backfill=True,
                coverage_kind="feed_snapshot",
            ),
        ))

        aapl = {
            row["source"]: row
            for row in repository.source_ticker_sync_states(
                ticker="AAPL", market="us"
            )
        }
        san = {
            row["source"]: row
            for row in repository.source_ticker_sync_states(
                ticker="SAN", market="es"
            )
        }

        self.assertEqual(set(aapl), {"sec", "news"})
        self.assertEqual(aapl["news"]["initial_status"], "complete")
        self.assertFalse(aapl["news"]["needs_backfill"])
        self.assertEqual(aapl["sec"]["initial_status"], "pending")
        self.assertTrue(aapl["sec"]["needs_backfill"])
        self.assertEqual(set(san), {"cnmv_hr", "bme_relevant_facts"})
        self.assertEqual(san["cnmv_hr"]["initial_status"], "complete")
        self.assertFalse(san["cnmv_hr"]["needs_backfill"])
        self.assertEqual(san["bme_relevant_facts"]["initial_status"], "pending")
        self.assertTrue(san["bme_relevant_facts"]["needs_backfill"])

    def test_initial_backfill_state_transitions_and_window_audit(self) -> None:
        repository = WebRepository(
            self.database_path,
            allowed_sources=("sec", "news", "cnmv_hr", "bme_relevant_facts"),
        )
        repository.record_collection_events((
            make_sync_event("sec", "AAPL", "us", "success", initial_backfill=True),
            make_sync_event("news", "MSFT", "us", "empty", initial_backfill=True),
            make_sync_event(
                "cnmv_hr",
                "SAN",
                "es",
                "partial",
                initial_backfill=True,
                effective_start=date(2026, 7, 2),
                error="feed=oir fixture blocked",
                coverage_kind="feed_snapshot",
            ),
            make_sync_event(
                "bme_relevant_facts",
                "SAN",
                "es",
                "failure",
                initial_backfill=True,
                effective_start=date(2026, 7, 2),
                error="fixture blocked",
                coverage_kind="bounded_window",
            ),
        ))
        rows = {
            (row["source"], row["ticker"], row["market"]): row
            for row in repository.source_ticker_sync_states()
        }

        self.assertEqual(rows[("sec", "AAPL", "us")]["initial_status"], "complete")
        self.assertEqual(rows[("news", "MSFT", "us")]["initial_status"], "complete")
        self.assertFalse(rows[("sec", "AAPL", "us")]["needs_backfill"])
        self.assertFalse(rows[("news", "MSFT", "us")]["needs_backfill"])
        self.assertEqual(rows[("cnmv_hr", "SAN", "es")]["initial_status"], "partial")
        self.assertEqual(
            rows[("bme_relevant_facts", "SAN", "es")]["initial_status"],
            "failure",
        )
        self.assertTrue(rows[("cnmv_hr", "SAN", "es")]["needs_backfill"])
        self.assertTrue(rows[("bme_relevant_facts", "SAN", "es")]["needs_backfill"])
        audited = rows[("cnmv_hr", "SAN", "es")]
        self.assertEqual(audited["last_status"], "partial")
        self.assertEqual(audited["coverage_kind"], "feed_snapshot")
        self.assertEqual(audited["requested_start_date"], "2025-08-01")
        self.assertEqual(audited["requested_end_date"], "2026-08-01")
        self.assertEqual(audited["effective_start_date"], "2026-07-02")
        self.assertEqual(audited["effective_end_date"], "2026-08-01")
        self.assertIsNotNone(audited["last_attempt_at"])
        # Partial means at least one sub-source succeeded, so this is a
        # successful (but incomplete) attempt timestamp.
        self.assertIsNotNone(audited["last_success_at"])
        self.assertIn("oir", audited["last_error"])
        self.assertIsNotNone(audited["updated_at"])

    def test_incremental_success_never_completes_pending_initial_backfill(self) -> None:
        repository = WebRepository(
            self.database_path,
            allowed_sources=("sec",),
        )
        repository.record_collection_events((
            make_sync_event(
                "sec",
                "AAPL",
                "us",
                "success",
                initial_backfill=False,
                requested_start=date(2026, 7, 25),
                effective_start=date(2026, 7, 25),
                coverage_kind="complete_window",
            ),
        ))

        pending = repository.source_ticker_sync_states(
            source="sec", ticker="AAPL", market="us"
        )[0]

        self.assertEqual(pending["initial_status"], "pending")
        self.assertTrue(pending["needs_backfill"])
        self.assertEqual(pending["last_status"], "success")
        self.assertEqual(pending["coverage_kind"], "complete_window")
        self.assertIsNotNone(pending["last_success_at"])

        repository.record_collection_events((
            make_sync_event("sec", "AAPL", "us", "empty", initial_backfill=True),
        ))
        complete = repository.source_ticker_sync_states(
            source="sec", ticker="AAPL", market="us"
        )[0]
        self.assertEqual(complete["initial_status"], "complete")
        self.assertFalse(complete["needs_backfill"])

    def test_company_search_matches_recorded_exchange(self) -> None:
        self.add_company("AAPL", "holdings")

        results = self.repository.search_companies("Nasdaq")

        self.assertEqual(results[0]["ticker"], "AAPL")
        self.assertEqual(results[0]["region"], "United States")

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

    def test_rolling_24_hour_filter_is_utc_half_open_not_eastern_calendar_day(self) -> None:
        self.add_company("AAPL", "holdings")
        start = datetime(2026, 8, 2, 3, tzinfo=timezone.utc)
        end = start + timedelta(hours=24)
        self.items.save([
            make_item("before-window", accepted_at="2026-08-02T02:59:59Z"),
            make_item("at-start", accepted_at=start.isoformat()),
            make_item("inside", accepted_at="2026-08-03T02:59:59Z"),
            make_item("at-end", accepted_at=end.isoformat()),
        ])

        result = self.repository.query_feed(FeedFilters(
            start_at=start,
            end_at=end,
        ))

        self.assertEqual(
            {item["external_id"] for item in result.items},
            {"at-start", "inside"},
        )
        # 03:00 UTC is still the prior date in New York, proving this is not
        # the legacy ET calendar-day boundary.
        self.assertEqual(
            next(item for item in result.items if item["external_id"] == "at-start")["effective_at"],
            start.isoformat(),
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
        self.repository.set_setting("extra_env:CUSTOM_TIMEOUT_SECONDS", "value-1")

        stored = self.repository.load_extra_env()
        status = self.repository.setting_status(("extra_env:CUSTOM_TIMEOUT_SECONDS",))[
            "extra_env:CUSTOM_TIMEOUT_SECONDS"
        ]

        self.assertEqual(stored, (("CUSTOM_TIMEOUT_SECONDS", "value-1"),))
        self.assertTrue(status["configured"])
        self.assertEqual(status["hint"], "••••ue-1")

        self.repository.set_setting("extra_env:CUSTOM_TIMEOUT_SECONDS", "")
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
            # Secret / URL / TLS override names must never be writable.
            "RESEARCH_AI_BASE_URL",
            "RESEARCH_AI_ALLOWED_HOSTS",
            "RESEARCH_AI_API_KEY",
            "FINNHUB_BASE_URL",
            "AU_UNIVERSE_VERIFY_SSL",
            "MY_APP_TOKEN",
            "XUEQIU_COOKIE",
            "SEC_USER_AGENT",
            # Not on the tuning whitelist.
            "CUSTOM_VAR",
        ):
            with self.assertRaises(ValueError, msg=bad_name):
                self.repository.set_setting(f"extra_env:{bad_name}", "x")

    def test_feed_page_is_capped_at_one_thousand(self) -> None:
        with self.assertRaises(ValueError):
            FeedFilters(page=1001)
        self.assertEqual(FeedFilters(page=1000).page, 1000)

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

    def test_news_status_latest_attempt_covers_any_news_source(self) -> None:
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
        repository.record_collection_events((SimpleNamespace(
            source="naver_news",
            ticker="005930",
            started_at=datetime(2026, 8, 2, 12, tzinfo=timezone.utc),
            finished_at=datetime(2026, 8, 2, 12, 0, 1, tzinfo=timezone.utc),
            status="success",
            records_read=1,
            records_written=1,
            records_inserted=1,
            records_updated=0,
            duplicate_records=0,
            error_message=None,
        ),))

        statuses = repository.source_statuses(
            now=datetime(2026, 8, 2, 14, tzinfo=timezone.utc)
        )

        news = next(
            record for record in statuses if record["type"] == "News"
        )
        self.assertIsNotNone(news["latest_attempt"])

    def test_news_status_includes_yahoo_uk_provider(self) -> None:
        repository = WebRepository(
            self.database_path,
            allowed_sources=("yahoo_uk",),
            known_sources=(
                SourceConfig(
                    name="yahoo_uk",
                    label="Yahoo Finance UK",
                    source_type="news",
                    enabled=True,
                ),
            ),
            implemented_sources=("yahoo_uk",),
        )
        self.items.save([
            make_item(
                "yahoo-1",
                source="yahoo_uk",
                source_type="news",
            )
        ])

        statuses = repository.source_statuses(
            now=datetime(2026, 8, 2, 14, tzinfo=timezone.utc)
        )

        news = next(
            record for record in statuses if record["type"] == "News"
        )
        self.assertEqual(news["status"], "connected")
        self.assertEqual(news["provider"], "Yahoo Finance UK")

    def test_list_unread_counts_only_today(self) -> None:
        self.add_company("AAPL", "holdings")
        self.items.save([
            make_item("today-1", accepted_at="2026-08-02T12:00:00+00:00"),
            make_item("today-2", accepted_at="2026-08-02T13:00:00+00:00"),
            make_item("old-1", accepted_at="2026-08-01T12:00:00+00:00"),
            make_item("old-read", accepted_at="2026-08-01T13:00:00+00:00"),
        ])
        old_read_id = next(
            item["id"]
            for item in self.repository.query_feed(FeedFilters()).items
            if item["external_id"] == "old-read"
        )
        self.repository.set_read((old_read_id,), True)

        counts = self.repository.counts(selected_date=date(2026, 8, 2))

        self.assertEqual(counts["list_unread"]["holdings"], 2)
        self.assertEqual(counts["unread"], 2)
        # The older unread item must not inflate today's badge.
        self.assertNotEqual(counts["list_unread"]["holdings"], 3)

    def test_filings_status_can_be_driven_by_investegate_items(self) -> None:
        repository = WebRepository(
            self.database_path,
            allowed_sources=("investegate",),
            known_sources=(
                SourceConfig(
                    name="investegate",
                    label="Investegate",
                    source_type="filings",
                    enabled=True,
                ),
            ),
            implemented_sources=("investegate",),
        )
        self.items.save([
            make_item(
                "investegate-1",
                source="investegate",
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
        self.assertEqual(filings["provider"], "Investegate")


if __name__ == "__main__":
    unittest.main()
