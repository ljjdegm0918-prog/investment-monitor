"""Acceptance tests for source × ticker × market initial-backfill state."""

from contextlib import contextmanager
from datetime import date, datetime, timedelta, timezone
from collections.abc import Iterable as IterableABC
import json
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory
from typing import get_args, get_origin, get_type_hints
import unittest

from investment_monitor.application import (
    ConfiguredCollectionResult,
    run_ticker_collection,
    run_workflow,
)
from investment_monitor.connectors.base import ConnectorUnavailableError
from investment_monitor.models import CollectionRequest, InformationItem
from investment_monitor.pipeline import CollectionEvent
from investment_monitor.registry import SourceRegistry
from investment_monitor.repository import SaveResult
from investment_monitor.sources.edinet import (
    EDINETConnector,
    EDINETRequestError,
    EDINETStore,
)
from investment_monitor.web import WebApplication
from investment_monitor.web_repository import WebRepository


@contextmanager
def open_database(path):
    """Open a SQLite connection that is closed on context exit.

    ``sqlite3.connect`` used directly as a context manager only commits or
    rolls back the transaction; it does not close the connection. On Windows
    the still-open connection keeps the database file locked, so the surrounding
    ``TemporaryDirectory`` cleanup fails with ``PermissionError`` (WinError 32)
    until the connection object is garbage collected. Closing explicitly here
    releases the file handle before the temporary directory is removed.
    """
    connection = sqlite3.connect(str(path))
    try:
        yield connection
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


class RecordingConnector:
    max_lookback_days = 30
    coverage_kind = "feed_snapshot"

    def __init__(self, name: str, calls: list) -> None:
        self.name = name
        self.calls = calls

    def collect(self, request: CollectionRequest):
        self.calls.append((self.name, request))
        return []


class MixedConnector:
    name = "healthy"
    max_lookback_days = 30

    def collect(self, request: CollectionRequest):
        ticker = request.tickers[0]
        if ticker == "MSFT":
            raise RuntimeError("healthy fixture failure")
        return []


class NamedRecordingConnector:
    max_lookback_days = 30

    def __init__(self, name: str, calls: list) -> None:
        self.name = name
        self.calls = calls

    def collect(self, request: CollectionRequest):
        self.calls.append(request)
        return []


class SourceWideFixtureConnector:
    source_wide_collection = True
    max_lookback_days = 3650

    def __init__(self, name: str, outcome: str) -> None:
        self.name = name
        self.outcome = outcome
        self.calls = []

    def collect(self, request: CollectionRequest):
        self.calls.append(request)
        if self.outcome == "failure":
            raise RuntimeError(f"{self.name} fixture failure")
        if self.outcome == "empty":
            return []
        return [InformationItem(
            source=self.name,
            source_type="regulatory_filing",
            external_id=f"{self.name}-fixture",
            tickers=("7203",),
            issuer="Toyota Motor Corporation",
            published_at=datetime(2026, 8, 1, tzinfo=timezone.utc),
            title="Official JP fixture",
            document_type="fixture",
            url="https://official.example.jp/fixture",
            collected_at=datetime(2026, 8, 2, tzinfo=timezone.utc),
            raw_metadata={"fixture": True},
            market="jp",
        )]


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

    def test_missing_selected_source_merges_with_normal_events_and_failures(self) -> None:
        self._write_settings(("healthy", "missing_fixture"))
        registry = SourceRegistry()
        registry.register("healthy", MixedConnector)

        result = run_ticker_collection(
            tickers=("AAPL", "MSFT"),
            settings_path=self.project_root / "config" / "settings.yaml",
            start_date=date(2026, 8, 1),
            end_date=date(2026, 8, 2),
            registry=registry,
            markets={"AAPL": "us", "MSFT": "us"},
            sources=("healthy", "missing_fixture"),
            initial_backfill=True,
        )

        self.assertEqual(
            {(failure.source, failure.ticker) for failure in result.failures},
            {
                ("healthy", "MSFT"),
                ("missing_fixture", "AAPL"),
                ("missing_fixture", "MSFT"),
            },
        )
        self.assertEqual(
            {(event.source, event.ticker, event.status) for event in result.events},
            {
                ("healthy", "AAPL", "empty"),
                ("healthy", "MSFT", "failure"),
                ("missing_fixture", "AAPL", "failure"),
                ("missing_fixture", "MSFT", "failure"),
            },
        )
        missing_events = [
            event for event in result.events
            if event.source == "missing_fixture"
        ]
        for event in missing_events:
            self.assertEqual(event.market, "us")
            self.assertEqual(event.requested_start_date, date(2026, 8, 1))
            self.assertEqual(event.requested_end_date, date(2026, 8, 2))
            self.assertEqual(event.effective_start_date, date(2026, 8, 1))
            self.assertEqual(event.effective_end_date, date(2026, 8, 2))
            self.assertEqual(event.coverage_kind, "unknown")
            self.assertTrue(event.initial_backfill)
            self.assertEqual(event.records_read, 0)
            self.assertEqual(event.records_written, 0)
            self.assertEqual(event.records_inserted, 0)
            self.assertEqual(event.records_updated, 0)
            self.assertEqual(event.duplicate_records, 0)
        states = WebRepository(
            result.database_path
        ).source_ticker_sync_states(source="missing_fixture")
        self.assertEqual(len(states), 2)
        self.assertTrue(all(row["initial_status"] == "failure" for row in states))
        self.assertTrue(all(row["last_status"] == "failure" for row in states))

    def test_configuration_missing_source_records_each_ticker_failure(self) -> None:
        self._write_settings(("config_fixture",))
        registry = SourceRegistry()

        def unavailable_factory():
            raise ConnectorUnavailableError("fixture credential missing")

        registry.register("config_fixture", unavailable_factory)

        result = run_ticker_collection(
            tickers=("AAPL", "MSFT"),
            settings_path=self.project_root / "config" / "settings.yaml",
            start_date=date(2026, 8, 1),
            end_date=date(2026, 8, 2),
            registry=registry,
            markets={"AAPL": "us", "MSFT": "us"},
            initial_backfill=True,
        )

        self.assertEqual(len(result.failures), 2)
        self.assertEqual(len(result.events), 2)
        self.assertEqual(
            {failure.ticker for failure in result.failures}, {"AAPL", "MSFT"}
        )
        for event in result.events:
            self.assertEqual(event.source, "config_fixture")
            self.assertEqual(event.status, "failure")
            self.assertEqual(event.market, "us")
            self.assertEqual(event.requested_start_date, date(2026, 8, 1))
            self.assertEqual(event.requested_end_date, date(2026, 8, 2))
            self.assertEqual(event.effective_start_date, date(2026, 8, 1))
            self.assertEqual(event.effective_end_date, date(2026, 8, 2))
            self.assertEqual(event.coverage_kind, "unknown")
            self.assertEqual(event.records_read, 0)
            self.assertEqual(event.records_written, 0)
            self.assertEqual(event.records_inserted, 0)
            self.assertEqual(event.records_updated, 0)
            self.assertEqual(event.duplicate_records, 0)
            self.assertTrue(event.initial_backfill)
        states = WebRepository(
            result.database_path
        ).source_ticker_sync_states(source="config_fixture")
        self.assertEqual(len(states), 2)
        self.assertTrue(all(row["initial_status"] == "failure" for row in states))
        self.assertTrue(all(row["last_status"] == "failure" for row in states))

    def test_collect_tickers_type_hints_resolve_sources_iterable(self) -> None:
        hints = get_type_hints(WebApplication.collect_tickers)
        source_hint = hints["sources"]
        optional_members = get_args(source_hint)
        iterable_hint = next(
            hint for hint in optional_members
            if get_origin(hint) is IterableABC
        )

        self.assertEqual(get_args(iterable_hint), (str,))

    def test_jp_source_wide_event_is_single_but_state_expands_per_ticker(self) -> None:
        expected_initial = {
            "success": "complete",
            "empty": "complete",
            "failure": "failure",
        }
        for source in ("tdnet_public_web", "edinet"):
            for outcome in ("success", "empty", "failure"):
                with self.subTest(source=source, outcome=outcome):
                    with TemporaryDirectory() as temporary_directory:
                        root = Path(temporary_directory)
                        (root / "config").mkdir()
                        (root / "data").mkdir()
                        settings_path = root / "config" / "settings.yaml"
                        settings_path.write_text(
                            "enabled_sources:\n"
                            f"  - {source}\n"
                            "database_path: ../data/web.sqlite3\n",
                            encoding="utf-8",
                        )
                        connector = SourceWideFixtureConnector(source, outcome)
                        registry = SourceRegistry()
                        registry.register(source, lambda: connector)

                        result = run_ticker_collection(
                            tickers=("7203", "6758"),
                            settings_path=settings_path,
                            start_date=date(2026, 8, 1),
                            end_date=date(2026, 8, 2),
                            registry=registry,
                            markets={"7203": "jp", "6758": "jp"},
                            initial_backfill=True,
                        )

                        self.assertEqual(len(connector.calls), 1)
                        self.assertEqual(connector.calls[0].tickers, ("7203", "6758"))
                        self.assertEqual(len(result.events), 1)
                        event = result.events[0]
                        self.assertEqual((event.source, event.ticker), (source, "*"))
                        self.assertEqual(event.status, outcome)
                        self.assertEqual(
                            event.records_read, 1 if outcome == "success" else 0
                        )
                        self.assertEqual(
                            len(result.failures), 1 if outcome == "failure" else 0
                        )
                        if result.failures:
                            self.assertEqual(result.failures[0].ticker, "*")
                        states = WebRepository(
                            result.database_path
                        ).source_ticker_sync_states(source=source, market="jp")
                        self.assertEqual(
                            {(row["ticker"], row["market"]) for row in states},
                            {("7203", "jp"), ("6758", "jp")},
                        )
                        self.assertTrue(all(
                            row["initial_status"] == expected_initial[outcome]
                            for row in states
                        ))
                        self.assertTrue(all(
                            row["last_status"] == outcome for row in states
                        ))
                        self.assertTrue(all(
                            row["needs_backfill"] == (outcome == "failure")
                            for row in states
                        ))
                        with open_database(result.database_path) as connection:
                            run = connection.execute(
                                "SELECT companies_processed, records_fetched, "
                                "successful_companies, failed_companies "
                                "FROM ingestion_runs WHERE source = ?",
                                (source,),
                            ).fetchone()
                            logs = connection.execute(
                                "SELECT ticker, records_read, records_written "
                                "FROM ingestion_logs WHERE source = ?",
                                (source,),
                            ).fetchall()
                        self.assertEqual(run[0], 1)
                        self.assertEqual(run[1], 1 if outcome == "success" else 0)
                        self.assertEqual(
                            run[2], 1 if outcome in {"success", "empty"} else 0
                        )
                        self.assertEqual(
                            run[3], 1 if outcome == "failure" else 0
                        )
                        self.assertEqual(len(logs), 1)
                        self.assertEqual(logs[0][0], "*")

    def test_known_jp_source_wide_state_targets_exclude_non_jp_tickers(self) -> None:
        for source in ("tdnet_public_web", "edinet"):
            with self.subTest(source=source):
                with TemporaryDirectory() as temporary_directory:
                    root = Path(temporary_directory)
                    (root / "config").mkdir()
                    (root / "data").mkdir()
                    settings_path = root / "config" / "settings.yaml"
                    settings_path.write_text(
                        "enabled_sources:\n"
                        f"  - {source}\n"
                        "database_path: ../data/web.sqlite3\n",
                        encoding="utf-8",
                    )
                    connector = SourceWideFixtureConnector(source, "success")
                    registry = SourceRegistry()
                    registry.register(source, lambda: connector)

                    result = run_ticker_collection(
                        tickers=("7203", "AAPL"),
                        settings_path=settings_path,
                        start_date=date(2026, 8, 1),
                        end_date=date(2026, 8, 2),
                        registry=registry,
                        markets={"7203": "jp", "AAPL": "us"},
                        initial_backfill=True,
                    )

                    states = WebRepository(
                        result.database_path
                    ).source_ticker_sync_states(source=source)
                    self.assertEqual(
                        {(row["ticker"], row["market"]) for row in states},
                        {("7203", "jp")},
                    )
                    self.assertEqual(len(result.events), 1)
                    self.assertEqual(result.events[0].ticker, "*")
                    self.assertEqual(result.events[0].records_read, 1)
                    with open_database(result.database_path) as connection:
                        run = connection.execute(
                            "SELECT companies_processed, records_fetched "
                            "FROM ingestion_runs WHERE source = ?",
                            (source,),
                        ).fetchone()
                        logs = connection.execute(
                            "SELECT ticker, records_read FROM ingestion_logs "
                            "WHERE source = ?",
                            (source,),
                        ).fetchall()
                    self.assertEqual(run, (1, 1))
                    self.assertEqual(logs, [("*", 1)])

    def test_known_jp_source_wide_us_only_creates_no_sync_state(self) -> None:
        for source in ("tdnet_public_web", "edinet"):
            with self.subTest(source=source):
                with TemporaryDirectory() as temporary_directory:
                    root = Path(temporary_directory)
                    (root / "config").mkdir()
                    (root / "data").mkdir()
                    settings_path = root / "config" / "settings.yaml"
                    settings_path.write_text(
                        "enabled_sources:\n"
                        f"  - {source}\n"
                        "database_path: ../data/web.sqlite3\n",
                        encoding="utf-8",
                    )
                    connector = SourceWideFixtureConnector(source, "empty")
                    registry = SourceRegistry()
                    registry.register(source, lambda: connector)

                    result = run_ticker_collection(
                        tickers=("AAPL", "MSFT"),
                        settings_path=settings_path,
                        start_date=date(2026, 8, 1),
                        end_date=date(2026, 8, 2),
                        registry=registry,
                        markets={"AAPL": "us", "MSFT": "us"},
                        initial_backfill=True,
                    )

                    states = WebRepository(
                        result.database_path
                    ).source_ticker_sync_states(source=source)
                    self.assertEqual(states, ())
                    self.assertEqual(len(result.events), 1)
                    self.assertEqual(
                        (result.events[0].ticker, result.events[0].status),
                        ("*", "empty"),
                    )
                    with open_database(result.database_path) as connection:
                        run = connection.execute(
                            "SELECT companies_processed, records_fetched "
                            "FROM ingestion_runs WHERE source = ?",
                            (source,),
                        ).fetchone()
                        logs = connection.execute(
                            "SELECT ticker, records_read FROM ingestion_logs "
                            "WHERE source = ?",
                            (source,),
                        ).fetchall()
                    self.assertEqual(run, (1, 0))
                    self.assertEqual(logs, [("*", 0)])

    def test_custom_source_wide_keeps_all_market_state_targets(self) -> None:
        source = "custom_source_wide"
        self._write_settings((source,))
        connector = SourceWideFixtureConnector(source, "empty")
        registry = SourceRegistry()
        registry.register(source, lambda: connector)

        result = run_ticker_collection(
            tickers=("7203", "AAPL"),
            settings_path=self.project_root / "config" / "settings.yaml",
            start_date=date(2026, 8, 1),
            end_date=date(2026, 8, 2),
            registry=registry,
            markets={"7203": "jp", "AAPL": "us"},
            initial_backfill=True,
        )

        states = WebRepository(
            result.database_path
        ).source_ticker_sync_states(source=source)
        self.assertEqual(
            {(row["ticker"], row["market"]) for row in states},
            {("7203", "jp"), ("AAPL", "us")},
        )
        self.assertTrue(all(row["initial_status"] == "complete" for row in states))
        self.assertEqual(len(result.events), 1)
        self.assertEqual(
            (result.events[0].ticker, result.events[0].status),
            ("*", "empty"),
        )
        with open_database(result.database_path) as connection:
            run = connection.execute(
                "SELECT companies_processed, records_fetched "
                "FROM ingestion_runs WHERE source = ?",
                (source,),
            ).fetchone()
            logs = connection.execute(
                "SELECT ticker, records_read FROM ingestion_logs "
                "WHERE source = ?",
                (source,),
            ).fetchall()
        self.assertEqual(run, (1, 0))
        self.assertEqual(logs, [("*", 0)])

    def test_unloaded_known_jp_sources_only_fail_for_jp_targets(self) -> None:
        for source in ("tdnet_public_web", "edinet"):
            for unavailable in (False, True):
                with self.subTest(source=source, unavailable=unavailable):
                    with TemporaryDirectory() as temporary_directory:
                        root = Path(temporary_directory)
                        (root / "config").mkdir()
                        (root / "data").mkdir()
                        settings_path = root / "config" / "settings.yaml"
                        settings_path.write_text(
                            "enabled_sources:\n"
                            f"  - {source}\n"
                            "database_path: ../data/web.sqlite3\n",
                            encoding="utf-8",
                        )
                        registry = SourceRegistry()
                        if unavailable:
                            def unavailable_factory():
                                raise ConnectorUnavailableError(
                                    "fixture configuration missing"
                                )
                            registry.register(source, unavailable_factory)

                        result = run_ticker_collection(
                            tickers=("7203", "AAPL"),
                            settings_path=settings_path,
                            start_date=date(2026, 8, 1),
                            end_date=date(2026, 8, 2),
                            registry=registry,
                            markets={"7203": "jp", "AAPL": "us"},
                            initial_backfill=True,
                        )

                        self.assertEqual(
                            [(failure.source, failure.ticker)
                             for failure in result.failures],
                            [(source, "7203")],
                        )
                        self.assertEqual(len(result.events), 1)
                        event = result.events[0]
                        self.assertEqual(
                            (event.source, event.ticker, event.market, event.status),
                            (source, "7203", "jp", "failure"),
                        )
                        states = WebRepository(
                            result.database_path
                        ).source_ticker_sync_states(source=source)
                        self.assertEqual(
                            {(row["ticker"], row["market"], row["last_status"])
                             for row in states},
                            {("7203", "jp", "failure")},
                        )
                        with open_database(result.database_path) as connection:
                            run = connection.execute(
                                "SELECT companies_processed, records_fetched "
                                "FROM ingestion_runs WHERE source = ?",
                                (source,),
                            ).fetchone()
                            logs = connection.execute(
                                "SELECT ticker, records_read FROM ingestion_logs "
                                "WHERE source = ?",
                                (source,),
                            ).fetchall()
                        self.assertEqual(run, (1, 0))
                        self.assertEqual(logs, [("7203", 0)])

    def test_unloaded_known_jp_sources_do_not_pollute_us_only_summary(self) -> None:
        for source in ("tdnet_public_web", "edinet"):
            for unavailable in (False, True):
                with self.subTest(source=source, unavailable=unavailable):
                    with TemporaryDirectory() as temporary_directory:
                        root = Path(temporary_directory)
                        (root / "config").mkdir()
                        (root / "data").mkdir()
                        (root / "config" / "universe.csv").write_text(
                            "ticker,list_type,market\nAAPL,holdings,us\n",
                            encoding="utf-8",
                        )
                        settings_path = root / "config" / "settings.yaml"
                        settings_path.write_text(
                            "enabled_sources:\n"
                            f"  - {source}\n"
                            "database_path: ../data/web.sqlite3\n",
                            encoding="utf-8",
                        )
                        registry = SourceRegistry()
                        if unavailable:
                            def unavailable_factory():
                                raise ConnectorUnavailableError(
                                    "fixture configuration missing"
                                )
                            registry.register(source, unavailable_factory)

                        def runner(**kwargs):
                            return run_ticker_collection(
                                registry=registry,
                                **kwargs,
                            )

                        application = WebApplication(
                            root, collection_runner=runner
                        )
                        summary = application.collect_tickers(
                            ("AAPL", "MSFT"),
                            lookback_days=1,
                            today=date(2026, 8, 2),
                            markets={"AAPL": "us", "MSFT": "us"},
                            sources=(source,),
                            initial_backfill=True,
                        )

                        self.assertEqual(summary["status"], "empty")
                        self.assertEqual(summary["failures"], [])
                        self.assertEqual(summary["records_fetched"], 0)
                        self.assertEqual(
                            application.repository.source_ticker_sync_states(
                                source=source
                            ),
                            (),
                        )
                        with open_database(
                            root / "data" / "web.sqlite3"
                        ) as connection:
                            run_count = connection.execute(
                                "SELECT COUNT(*) FROM ingestion_runs "
                                "WHERE source = ?",
                                (source,),
                            ).fetchone()[0]
                            log_count = connection.execute(
                                "SELECT COUNT(*) FROM ingestion_logs "
                                "WHERE source = ?",
                                (source,),
                            ).fetchone()[0]
                        self.assertEqual((run_count, log_count), (0, 0))

    def test_unloaded_unknown_sources_keep_all_market_targets(self) -> None:
        for unavailable in (False, True):
            with self.subTest(unavailable=unavailable):
                source = (
                    "custom_unavailable" if unavailable else "custom_missing"
                )
                self._write_settings((source,))
                registry = SourceRegistry()
                if unavailable:
                    def unavailable_factory():
                        raise ConnectorUnavailableError(
                            "fixture configuration missing"
                        )
                    registry.register(source, unavailable_factory)

                result = run_ticker_collection(
                    tickers=("7203", "AAPL"),
                    settings_path=self.project_root / "config" / "settings.yaml",
                    start_date=date(2026, 8, 1),
                    end_date=date(2026, 8, 2),
                    registry=registry,
                    markets={"7203": "jp", "AAPL": "us"},
                    initial_backfill=True,
                )

                self.assertEqual(
                    {failure.ticker for failure in result.failures},
                    {"7203", "AAPL"},
                )
                self.assertEqual(
                    {(event.ticker, event.market, event.status)
                     for event in result.events},
                    {
                        ("7203", "jp", "failure"),
                        ("AAPL", "us", "failure"),
                    },
                )
                states = WebRepository(
                    result.database_path
                ).source_ticker_sync_states(source=source)
                self.assertEqual(
                    {(row["ticker"], row["market"]) for row in states},
                    {("7203", "jp"), ("AAPL", "us")},
                )

    def test_edinet_partial_day_failure_keeps_items_and_one_real_event(self) -> None:
        self._write_settings(("edinet",))

        class PartialEdinetClient:
            def list_documents(self, day):
                if day == date(2026, 8, 8):
                    raise EDINETRequestError("2026-08-08 fixture blocked", 503)
                return {"results": [{
                    "docID": "EDINET-PARTIAL-1",
                    "edinetCode": "E00001",
                    "secCode": "72030",
                    "JCN": "1234567890123",
                    "filerName": "Toyota Motor Corporation",
                    "docTypeCode": "120",
                    "docDescription": "Annual report fixture",
                    "submitDateTime": "2026-08-07 13:00",
                    "withdrawalStatus": "0",
                }]}

        connector = EDINETConnector(
            PartialEdinetClient(),
            EDINETStore(self.project_root / "data" / "edinet.sqlite3"),
            cache_ttl=timedelta(seconds=60),
            download_root=self.project_root / "data" / "downloads",
            now=lambda: datetime(2026, 8, 8, 3, tzinfo=timezone.utc),
        )
        registry = SourceRegistry()
        registry.register("edinet", lambda: connector)

        result = run_ticker_collection(
            tickers=("7203", "6758"),
            settings_path=self.project_root / "config" / "settings.yaml",
            start_date=date(2026, 8, 7),
            end_date=date(2026, 8, 8),
            registry=registry,
            markets={"7203": "jp", "6758": "jp"},
            initial_backfill=True,
        )

        self.assertEqual(len(result.items), 1)
        self.assertEqual(len(result.failures), 1)
        failure = result.failures[0]
        self.assertEqual((failure.source, failure.ticker), ("edinet", "*"))
        self.assertEqual(failure.feed, "2026-08-08")
        self.assertIn("fixture blocked", failure.message)
        self.assertEqual(len(result.events), 1)
        event = result.events[0]
        self.assertEqual((event.ticker, event.status), ("*", "partial"))
        self.assertEqual(event.records_read, 1)
        self.assertIn("2026-08-08", event.error_message)
        states = WebRepository(
            result.database_path
        ).source_ticker_sync_states(source="edinet", market="jp")
        self.assertEqual({row["ticker"] for row in states}, {"7203", "6758"})
        self.assertTrue(all(row["initial_status"] == "partial" for row in states))
        self.assertTrue(all(row["last_status"] == "partial" for row in states))
        self.assertTrue(all(row["needs_backfill"] for row in states))
        with open_database(result.database_path) as connection:
            run = connection.execute(
                "SELECT status, companies_processed, failed_companies, "
                "records_fetched FROM ingestion_runs WHERE source='edinet'"
            ).fetchone()
            logs = connection.execute(
                "SELECT ticker, status, records_read FROM ingestion_logs "
                "WHERE source='edinet'"
            ).fetchall()
        self.assertEqual(run, ("partial", 1, 1, 1))
        self.assertEqual(logs, [("*", "partial", 1)])

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

    def test_known_ordinary_connectors_only_receive_their_market_tickers(self) -> None:
        scenarios = (
            ("sec", ("AAPL", "SAN"), {"AAPL": "us", "SAN": "es"}, "AAPL"),
            (
                "eqs_dgap",
                ("SAP", "AAPL"),
                {"SAP": "de", "AAPL": "us"},
                "SAP",
            ),
        )
        for source, tickers, markets, expected_ticker in scenarios:
            with self.subTest(source=source):
                self._write_settings((source,))
                calls = []
                registry = SourceRegistry()
                registry.register(
                    source,
                    lambda source=source, calls=calls: NamedRecordingConnector(
                        source, calls
                    ),
                )

                result = run_ticker_collection(
                    tickers=tickers,
                    settings_path=self.project_root / "config" / "settings.yaml",
                    start_date=date(2026, 8, 1),
                    end_date=date(2026, 8, 2),
                    registry=registry,
                    markets=markets,
                    initial_backfill=True,
                )

                self.assertEqual(
                    [request.tickers for request in calls],
                    [(expected_ticker,)],
                )
                self.assertEqual(result.failures, ())
                self.assertEqual(len(result.events), 1)
                self.assertEqual(
                    (result.events[0].source, result.events[0].ticker),
                    (source, expected_ticker),
                )
                states = WebRepository(
                    result.database_path
                ).source_ticker_sync_states(source=source)
                self.assertEqual(
                    {(row["ticker"], row["market"]) for row in states},
                    {(expected_ticker, markets[expected_ticker])},
                )

    def test_foreign_only_known_connector_does_not_pollute_summary_or_activity(self) -> None:
        scenarios = (
            ("sec", "SAN", "es"),
            ("eqs_dgap", "AAPL", "us"),
        )
        for source, ticker, market in scenarios:
            with self.subTest(source=source):
                with TemporaryDirectory() as temporary_directory:
                    root = Path(temporary_directory)
                    (root / "config").mkdir()
                    (root / "data").mkdir()
                    (root / "config" / "universe.csv").write_text(
                        "ticker,list_type,market\n"
                        f"{ticker},holdings,{market}\n",
                        encoding="utf-8",
                    )
                    (root / "config" / "settings.yaml").write_text(
                        "enabled_sources:\n"
                        f"  - {source}\n"
                        "database_path: ../data/web.sqlite3\n",
                        encoding="utf-8",
                    )
                    calls = []
                    registry = SourceRegistry()
                    registry.register(
                        source,
                        lambda source=source, calls=calls: NamedRecordingConnector(
                            source, calls
                        ),
                    )

                    def runner(**kwargs):
                        return run_ticker_collection(registry=registry, **kwargs)

                    application = WebApplication(root, collection_runner=runner)
                    summary = application.collect_tickers(
                        (ticker,),
                        lookback_days=1,
                        today=date(2026, 8, 2),
                        markets={ticker: market},
                        sources=(source,),
                        initial_backfill=True,
                    )

                    self.assertEqual(calls, [])
                    self.assertEqual(summary["status"], "empty")
                    self.assertEqual(summary["failures"], [])
                    self.assertEqual(summary["records_fetched"], 0)
                    self.assertEqual(
                        application.repository.source_ticker_sync_states(
                            source=source
                        ),
                        (),
                    )
                    with open_database(
                        root / "data" / "web.sqlite3"
                    ) as connection:
                        run_count = connection.execute(
                            "SELECT COUNT(*) FROM ingestion_runs WHERE source = ?",
                            (source,),
                        ).fetchone()[0]
                        log_count = connection.execute(
                            "SELECT COUNT(*) FROM ingestion_logs WHERE source = ?",
                            (source,),
                        ).fetchone()[0]
                    self.assertEqual((run_count, log_count), (0, 0))

    def test_run_workflow_filters_known_connector_by_market(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            universe_path = root / "universe.csv"
            universe_path.write_text(
                "ticker,list_type,market\n"
                "AAPL,holdings,us\n"
                "SAN,watchlist,es\n",
                encoding="utf-8",
            )
            settings_path = root / "settings.yaml"
            settings_path.write_text(
                "enabled_sources:\n"
                "  - sec\n"
                "database_path: data/items.sqlite3\n",
                encoding="utf-8",
            )
            calls = []
            registry = SourceRegistry()
            registry.register(
                "sec", lambda: NamedRecordingConnector("sec", calls)
            )

            result = run_workflow(
                universe_path=universe_path,
                settings_path=settings_path,
                start_date=date(2026, 8, 1),
                end_date=date(2026, 8, 2),
                output_path=root / "report.html",
                registry=registry,
            )

            self.assertEqual(
                [request.tickers for request in calls], [("AAPL",)]
            )
            self.assertEqual(result.failure_count, 0)
            states = WebRepository(
                root / "data" / "items.sqlite3"
            ).source_ticker_sync_states(source="sec")
            self.assertEqual(
                {(row["ticker"], row["market"]) for row in states},
                {("AAPL", "us")},
            )

    def test_missing_market_map_keeps_legacy_sec_collection(self) -> None:
        self._write_settings(("sec",))
        calls = []
        registry = SourceRegistry()
        registry.register(
            "sec", lambda: NamedRecordingConnector("sec", calls)
        )

        result = run_ticker_collection(
            tickers=("AAPL",),
            settings_path=self.project_root / "config" / "settings.yaml",
            start_date=date(2026, 8, 1),
            end_date=date(2026, 8, 2),
            registry=registry,
        )

        self.assertEqual([request.tickers for request in calls], [("AAPL",)])
        self.assertEqual(len(result.events), 1)
        self.assertEqual(result.events[0].ticker, "AAPL")
        self.assertEqual(result.failures, ())

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
        with open_database(
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
