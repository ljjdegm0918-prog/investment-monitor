"""Acceptance tests for source × ticker × market initial-backfill state."""

from datetime import date, datetime, timezone
import json
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory
import unittest

from investment_monitor.application import (
    ConfiguredCollectionResult,
    run_ticker_collection,
)
from investment_monitor.models import CollectionRequest
from investment_monitor.pipeline import CollectionEvent
from investment_monitor.registry import SourceRegistry
from investment_monitor.repository import SaveResult
from investment_monitor.web import WebApplication
from investment_monitor.web_repository import WebRepository


class RecordingConnector:
    max_lookback_days = 30
    coverage_kind = "feed_snapshot"

    def __init__(self, name: str, calls: list) -> None:
        self.name = name
        self.calls = calls

    def collect(self, request: CollectionRequest):
        self.calls.append((self.name, request))
        return []


class SourceBackfillStateTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = TemporaryDirectory()
        self.addCleanup(self.temporary_directory.cleanup)
        self.project_root = Path(self.temporary_directory.name)
        (self.project_root / "config").mkdir()
        (self.project_root / "data").mkdir()
        (self.project_root / "config" / "universe.csv").write_text(
            "ticker,list_type,market\nAAPL,holdings,us\n",
            encoding="utf-8",
        )
        cache_directory = self.project_root / ".cache" / "investment_monitor"
        cache_directory.mkdir(parents=True)
        (cache_directory / "company_tickers.json").write_text(
            json.dumps({
                "0": {
                    "cik_str": 320193,
                    "ticker": "AAPL",
                    "title": "Apple Inc.",
                },
                "1": {
                    "cik_str": 1045810,
                    "ticker": "NVDA",
                    "title": "NVIDIA CORP",
                },
            }),
            encoding="utf-8",
        )

    def _write_settings(self, sources) -> None:
        enabled = "".join(f"  - {source}\n" for source in sources)
        (self.project_root / "config" / "settings.yaml").write_text(
            f"enabled_sources:\n{enabled}"
            "database_path: ../data/web.sqlite3\n",
            encoding="utf-8",
        )

    def test_run_ticker_collection_filters_sources_and_audits_windows(self) -> None:
        self._write_settings(("sec", "cnmv_hr"))
        calls = []
        registry = SourceRegistry()
        registry.register("sec", lambda: RecordingConnector("sec", calls))
        registry.register(
            "cnmv_hr", lambda: RecordingConnector("cnmv_hr", calls)
        )

        result = run_ticker_collection(
            tickers=("AAPL",),
            settings_path=self.project_root / "config" / "settings.yaml",
            start_date=date(2025, 8, 1),
            end_date=date(2026, 8, 1),
            registry=registry,
            markets={"AAPL": "us"},
            sources=("sec",),
            initial_backfill=True,
        )

        self.assertEqual([name for name, _ in calls], ["sec"])
        self.assertEqual(len(result.events), 1)
        event = result.events[0]
        self.assertEqual(event.source, "sec")
        self.assertEqual(event.ticker, "AAPL")
        self.assertEqual(event.market, "us")
        self.assertTrue(event.initial_backfill)
        self.assertEqual(event.coverage_kind, "feed_snapshot")
        self.assertEqual(event.requested_start_date, date(2025, 8, 1))
        self.assertEqual(event.requested_end_date, date(2026, 8, 1))
        self.assertEqual(event.effective_start_date, date(2026, 7, 2))
        self.assertEqual(event.effective_end_date, date(2026, 8, 1))

    def test_add_filters_initial_backfill_to_market_relevant_sources(self) -> None:
        self._write_settings(("sec", "cnmv_hr", "bme_relevant_facts"))
        calls = []

        def runner(**kwargs):
            calls.append(kwargs)
            source = tuple(kwargs["sources"])[0]
            now = datetime(2026, 8, 1, 12, tzinfo=timezone.utc)
            event = CollectionEvent(
                source=source,
                ticker=tuple(kwargs["tickers"])[0],
                started_at=now,
                finished_at=now,
                status="empty",
                records_read=0,
                records_written=0,
                records_inserted=0,
                records_updated=0,
                duplicate_records=0,
                market=next(iter(kwargs["markets"].values())),
                requested_start_date=kwargs["start_date"],
                requested_end_date=kwargs["end_date"],
                effective_start_date=kwargs["start_date"],
                effective_end_date=kwargs["end_date"],
                coverage_kind="complete_window",
                initial_backfill=kwargs["initial_backfill"],
            )
            return ConfiguredCollectionResult(
                items=(),
                failures=(),
                save_result=SaveResult(),
                database_path=self.project_root / "data" / "web.sqlite3",
                stored_count=0,
                events=(event,),
            )

        application = WebApplication(self.project_root, collection_runner=runner)
        response = application.handle(
            "POST",
            "/api/companies/batch",
            json.dumps({
                "tickers": "NVDA",
                "lists": ["holdings"],
                "market": "us",
            }).encode(),
        )

        self.assertEqual(response.status, 201)
        self.assertEqual(len(calls), 1)
        self.assertEqual(tuple(calls[0]["sources"]), ("sec",))
        self.assertTrue(calls[0]["initial_backfill"])
        self.assertEqual(
            (calls[0]["end_date"] - calls[0]["start_date"]).days,
            365,
        )

    def test_es_add_runs_each_relevant_source_without_sec(self) -> None:
        self._write_settings(("sec", "cnmv_hr", "bme_relevant_facts"))
        calls = []

        def runner(**kwargs):
            calls.append(kwargs)
            return ConfiguredCollectionResult(
                items=(),
                failures=(),
                save_result=SaveResult(),
                database_path=self.project_root / "data" / "web.sqlite3",
                stored_count=0,
                events=(),
            )

        application = WebApplication(self.project_root, collection_runner=runner)
        response = application.handle(
            "POST",
            "/api/companies/batch",
            json.dumps({
                "tickers": "SAN",
                "lists": ["holdings"],
                "market": "es",
            }).encode(),
        )

        self.assertEqual(response.status, 201)
        self.assertEqual(
            [tuple(call["sources"]) for call in calls],
            [("cnmv_hr",), ("bme_relevant_facts",)],
        )
        self.assertTrue(all(call["initial_backfill"] for call in calls))

    def test_existing_pending_company_stays_incremental_until_explicit_backfill(self) -> None:
        self._write_settings(("sec",))
        calls = []
        application_holder = {}

        def runner(**kwargs):
            calls.append(kwargs)
            now = datetime(2026, 8, 1, 12, tzinfo=timezone.utc)
            event = CollectionEvent(
                source="sec",
                ticker="AAPL",
                started_at=now,
                finished_at=now,
                status="empty" if kwargs["initial_backfill"] else "success",
                records_read=0,
                records_written=0,
                records_inserted=0,
                records_updated=0,
                duplicate_records=0,
                market="us",
                requested_start_date=kwargs["start_date"],
                requested_end_date=kwargs["end_date"],
                effective_start_date=kwargs["start_date"],
                effective_end_date=kwargs["end_date"],
                coverage_kind="complete_window",
                initial_backfill=kwargs["initial_backfill"],
            )
            application_holder["application"].repository.record_collection_events(
                (event,)
            )
            return ConfiguredCollectionResult(
                items=(),
                failures=(),
                save_result=SaveResult(),
                database_path=self.project_root / "data" / "web.sqlite3",
                stored_count=0,
                events=(event,),
            )

        application = WebApplication(self.project_root, collection_runner=runner)
        application_holder["application"] = application
        # Remove the new table to reproduce a DB created before sync-state
        # migration. Reopening must recreate pending state without historical I/O.
        with sqlite3.connect(
            self.project_root / "data" / "web.sqlite3"
        ) as connection:
            connection.execute("DROP TABLE source_ticker_sync_state")
        application = WebApplication(self.project_root, collection_runner=runner)
        application_holder["application"] = application

        application.collect_active_companies(
            lookback_days=7,
            today=date(2026, 8, 1),
        )

        self.assertEqual(len(calls), 1)
        self.assertFalse(calls[0]["initial_backfill"])
        self.assertEqual(tuple(calls[0]["sources"]), ("sec",))
        self.assertEqual((calls[0]["end_date"] - calls[0]["start_date"]).days, 7)
        pending = application.repository.source_ticker_sync_states(
            source="sec", ticker="AAPL", market="us"
        )[0]
        self.assertTrue(pending["needs_backfill"])
        self.assertEqual(pending["initial_status"], "pending")
        self.assertEqual(pending["last_status"], "success")

        application.collect_tickers(
            ("AAPL",),
            lookback_days=365,
            today=date(2026, 8, 1),
            markets={"AAPL": "us"},
            sources=("sec",),
            initial_backfill=True,
        )
        complete = application.repository.source_ticker_sync_states(
            source="sec", ticker="AAPL", market="us"
        )[0]
        self.assertFalse(complete["needs_backfill"])
        self.assertEqual(complete["initial_status"], "complete")

        application.collect_active_companies(
            lookback_days=7,
            today=date(2026, 8, 2),
        )
        self.assertEqual(len(calls), 3)
        self.assertTrue(calls[1]["initial_backfill"])
        self.assertFalse(calls[2]["initial_backfill"])
        self.assertEqual((calls[2]["end_date"] - calls[2]["start_date"]).days, 7)


if __name__ == "__main__":
    unittest.main()
