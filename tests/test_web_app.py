import json
import os
from datetime import date, datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from investment_monitor.application import ConfiguredCollectionResult
from investment_monitor.web import DailyCollectionScheduler, WebApplication
from investment_monitor.models import InformationItem
from investment_monitor.repository import SaveResult
from investment_monitor.sqlite_repository import SQLiteInformationRepository


class WebApplicationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = TemporaryDirectory()
        self.project_root = Path(self.temporary_directory.name)
        (self.project_root / "config").mkdir()
        (self.project_root / "data").mkdir()
        (self.project_root / "config" / "settings.yaml").write_text(
            "enabled_sources:\n  - sec\ndatabase_path: ../data/web.sqlite3\n",
            encoding="utf-8",
        )
        (self.project_root / "config" / "universe.csv").write_text(
            "ticker,list_type\nAAPL,holdings\n", encoding="utf-8"
        )
        cache_directory = self.project_root / ".cache" / "investment_monitor"
        cache_directory.mkdir(parents=True)
        (cache_directory / "company_tickers.json").write_text(json.dumps({
            "0": {"cik_str": 320193, "ticker": "AAPL", "title": "Apple Inc."},
            "1": {"cik_str": 789019, "ticker": "MSFT", "title": "Microsoft Corporation"},
            "2": {"cik_str": 1045810, "ticker": "NVDA", "title": "NVIDIA CORP"},
        }), encoding="utf-8")

        # The established repository creates the generic InformationItem tables.
        self.items = SQLiteInformationRepository(self.project_root / "data" / "web.sqlite3")
        self.collection_calls = []
        self.application = WebApplication(
            self.project_root,
            collection_runner=self.noop_collection_runner,
        )

    def tearDown(self) -> None:
        self.temporary_directory.cleanup()

    def payload(self, response):
        return json.loads(response.body.decode("utf-8"))

    def noop_collection_runner(self, **kwargs):
        self.collection_calls.append(kwargs)
        return ConfiguredCollectionResult(
            items=(),
            failures=(),
            save_result=SaveResult(),
            database_path=self.project_root / "data" / "web.sqlite3",
            stored_count=self.items.count(),
        )

    def test_core_pages_and_static_assets_are_served(self) -> None:
        page = self.application.handle("GET", "/today")
        script = self.application.handle("GET", "/static/app.js")
        favicon = self.application.handle("GET", "/favicon.ico")

        self.assertEqual(page.status, 200)
        self.assertIn(b"Investment Monitor", page.body)
        self.assertIn(b'data-view="today"', page.body)
        self.assertEqual(script.status, 200)
        self.assertEqual(favicon.status, 204)
        self.assertIn(b'target="_blank" rel="noopener noreferrer"', script.body)
        self.assertIn(b"function renderFatal", script.body)
        for state_text in (
            b"Loading information",
            b"No information for this date",
            b"Search returned no results",
            b"This source is not configured",
            b"Request failed",
        ):
            self.assertIn(state_text, script.body)

    def test_bootstrap_uses_fixed_lists_and_truthful_source_status(self) -> None:
        response = self.application.handle("GET", "/api/bootstrap")
        payload = self.payload(response)

        self.assertEqual(response.status, 200)
        self.assertEqual([record["slug"] for record in payload["lists"]], ["holdings", "planned", "watchlist"])
        self.assertEqual(payload["sources"][0]["status"], "unavailable")
        self.assertEqual(payload["sources"][1]["status"], "not_connected")
        self.assertEqual(payload["sources"][2]["status"], "not_connected")
        self.assertEqual(payload["sources"][3]["status"], "not_connected")
        self.assertEqual(payload["sources"][3]["type"], "Research")

    def test_initial_csv_does_not_restore_removed_memberships_on_restart(self) -> None:
        removed = self.application.handle(
            "POST",
            "/api/companies/remove-all",
            json.dumps({"ticker": "AAPL"}).encode(),
        )
        reopened = WebApplication(
            self.project_root,
            collection_runner=self.noop_collection_runner,
        )

        self.assertEqual(removed.status, 200)
        self.assertEqual(reopened.repository.active_tickers(), ())

    def test_disconnected_source_filter_has_explicit_empty_state(self) -> None:
        response = self.application.handle("GET", "/api/feed?type=community")
        payload = self.payload(response)

        self.assertEqual(response.status, 200)
        self.assertEqual(payload["items"], [])
        self.assertEqual(payload["disconnected_message"], "Community source not connected")

    def test_research_filter_has_explicit_empty_state(self) -> None:
        response = self.application.handle("GET", "/api/feed?type=research")
        payload = self.payload(response)

        self.assertEqual(response.status, 200)
        self.assertEqual(payload["items"], [])
        self.assertEqual(payload["disconnected_message"], "Research source not connected")

    def test_invalid_filter_returns_clear_client_error(self) -> None:
        response = self.application.handle("GET", "/api/feed?start_date=2026-08-03&end_date=2026-08-02")

        self.assertEqual(response.status, 400)
        self.assertIn("start_date", self.payload(response)["error"])

    def test_boolean_mutations_require_real_json_booleans(self) -> None:
        response = self.application.handle(
            "POST",
            "/api/read",
            json.dumps({"item_ids": [1], "is_read": "false"}).encode("utf-8"),
        )

        self.assertEqual(response.status, 400)
        self.assertIn("JSON boolean", self.payload(response)["error"])

    def test_mock_source_configuration_cannot_enable_mock_production_records(self) -> None:
        (self.project_root / "config" / "settings.yaml").write_text(
            "enabled_sources:\n  - sec\n  - mock_community\ndatabase_path: ../data/web.sqlite3\n",
            encoding="utf-8",
        )

        application = WebApplication(self.project_root)

        self.assertEqual(application.enabled_sources, ("sec",))

    def test_news_enabled_without_api_key_stays_not_connected(self) -> None:
        (self.project_root / "config" / "settings.yaml").write_text(
            "enabled_sources:\n  - sec\n  - news\n"
            "database_path: ../data/web.sqlite3\n",
            encoding="utf-8",
        )
        with patch.dict(os.environ, {"FINNHUB_API_KEY": ""}, clear=False):
            application = WebApplication(
                self.project_root,
                collection_runner=self.noop_collection_runner,
            )
            statuses = application.repository.source_statuses()
            news = next(
                record for record in statuses if record["type"] == "News"
            )
            feed = self.payload(
                application.handle("GET", "/api/feed?type=news")
            )

        self.assertEqual(news["status"], "not_connected")
        self.assertIn("FINNHUB_API_KEY", news["last_failure"])
        self.assertEqual(feed["items"], [])
        self.assertEqual(
            feed["disconnected_message"],
            "News source not connected",
        )

    def test_news_enabled_with_api_key_is_implemented_and_waiting(self) -> None:
        (self.project_root / "config" / "settings.yaml").write_text(
            "enabled_sources:\n  - sec\n  - news\n"
            "database_path: ../data/web.sqlite3\n",
            encoding="utf-8",
        )
        with patch.dict(
            os.environ,
            {"FINNHUB_API_KEY": "test-key"},
            clear=False,
        ):
            application = WebApplication(
                self.project_root,
                collection_runner=self.noop_collection_runner,
            )
            statuses = application.repository.source_statuses()
            news = next(
                record for record in statuses if record["type"] == "News"
            )

        self.assertEqual(news["status"], "unavailable")
        self.assertIsNone(news["last_failure"])

    def test_http_workflow_covers_batch_memberships_feed_read_and_search(self) -> None:
        self.items.save([InformationItem(
            source="sec",
            source_type="regulatory_filing",
            external_id="0000320193-26-000001",
            tickers=("AAPL",),
            issuer="Apple Inc.",
            published_at=datetime(2026, 8, 2, tzinfo=timezone.utc),
            title="Quarterly Report on Form 10-Q",
            document_type="10-Q",
            url="https://www.sec.gov/Archives/aapl.htm",
            collected_at=datetime(2026, 8, 2, 13, tzinfo=timezone.utc),
            raw_metadata={"acceptanceDateTime": "2026-08-02T12:45:00Z"},
        )])
        memberships = self.payload(self.application.handle(
            "POST",
            "/api/companies/batch",
            json.dumps({"tickers": "aapl", "lists": ["planned", "watchlist"]}).encode(),
        ))
        mixed_batch = self.payload(self.application.handle(
            "POST",
            "/api/companies/batch",
            json.dumps({"tickers": "MSFT BAD", "lists": ["holdings"]}).encode(),
        ))
        feed = self.payload(self.application.handle(
            "GET",
            "/api/feed?start_date=2026-08-02&end_date=2026-08-02&q=10-Q&list=holdings",
        ))
        item_id = feed["items"][0]["id"]
        marked = self.application.handle(
            "POST", "/api/read", json.dumps({"item_ids": [item_id], "is_read": True}).encode()
        )
        read_feed = self.payload(self.application.handle(
            "GET", "/api/feed?read=read&q=10-Q&list=holdings"
        ))
        unmarked = self.application.handle(
            "POST", "/api/read", json.dumps({"item_ids": [item_id], "is_read": False}).encode()
        )

        self.assertEqual([record["ticker"] for record in memberships["added"]], ["AAPL"])
        self.assertEqual([record["ticker"] for record in mixed_batch["added"]], ["MSFT"])
        self.assertEqual([record["ticker"] for record in mixed_batch["failed"]], ["BAD"])
        self.assertEqual(feed["pagination"]["total"], 1)
        self.assertEqual(feed["items"][0]["list_slugs"], ["holdings", "planned", "watchlist"])
        self.assertEqual(marked.status, 200)
        self.assertTrue(read_feed["items"][0]["is_read"])
        self.assertEqual(unmarked.status, 200)

    def test_adding_nvda_immediately_backfills_sec_items(self) -> None:
        def nvda_collection_runner(**kwargs):
            self.collection_calls.append(kwargs)
            item = InformationItem(
                source="sec",
                source_type="regulatory_filing",
                external_id="0001045810-26-000060",
                tickers=("NVDA",),
                issuer="NVIDIA CORP",
                published_at=datetime(2026, 7, 2, tzinfo=timezone.utc),
                title="Form 8-K Current Report",
                document_type="8-K",
                url="https://www.sec.gov/Archives/edgar/data/1045810/000104581026000060/nvda-20260628.htm",
                collected_at=datetime(2026, 8, 3, tzinfo=timezone.utc),
                raw_metadata={"acceptanceDateTime": "2026-07-02T09:23:16-04:00"},
            )
            save_result = self.items.save((item,))
            return ConfiguredCollectionResult(
                items=(item,),
                failures=(),
                save_result=save_result,
                database_path=self.project_root / "data" / "web.sqlite3",
                stored_count=self.items.count(),
            )

        application = WebApplication(
            self.project_root,
            collection_runner=nvda_collection_runner,
        )
        response = application.handle(
            "POST",
            "/api/companies/batch",
            json.dumps({"tickers": "NVDA", "lists": ["holdings"]}).encode(),
        )
        payload = self.payload(response)
        feed = self.payload(application.handle("GET", "/api/feed?ticker=NVDA"))

        self.assertEqual(response.status, 201)
        self.assertEqual(payload["collection"]["status"], "success")
        self.assertEqual(payload["collection"]["inserted"], 1)
        self.assertEqual(self.collection_calls[-1]["tickers"], ("NVDA",))
        self.assertEqual(
            (self.collection_calls[-1]["end_date"] - self.collection_calls[-1]["start_date"]).days,
            365,
        )
        self.assertEqual(feed["pagination"]["total"], 1)
        self.assertEqual(feed["items"][0]["external_id"], "0001045810-26-000060")

    def test_daily_scheduler_collects_all_active_database_tickers_once_per_day(self) -> None:
        self.application.repository.add_companies_batch(
            "NVDA", ("watchlist",), self.application.resolver
        )
        self.items.save((InformationItem(
            source="sec",
            source_type="regulatory_filing",
            external_id="existing-aapl",
            tickers=("AAPL",),
            issuer="Apple Inc.",
            published_at=datetime(2026, 8, 1, tzinfo=timezone.utc),
            title="Existing filing",
            document_type="8-K",
            url="https://www.sec.gov/Archives/existing-aapl.htm",
            collected_at=datetime(2026, 8, 2, tzinfo=timezone.utc),
            raw_metadata={},
        ),))
        scheduler = DailyCollectionScheduler(
            self.application,
            hour_et=6,
            lookback_days=7,
        )
        current = datetime(2026, 8, 3, 12, tzinfo=timezone.utc)

        first_run = scheduler.run_due_now(current)
        second_run = scheduler.run_due_now(current)

        self.assertTrue(first_run)
        self.assertFalse(second_run)
        self.assertEqual(len(self.collection_calls), 2)
        calls_by_ticker = {
            call["tickers"]: call for call in self.collection_calls
        }
        self.assertEqual(
            calls_by_ticker[("NVDA",)]["start_date"], date(2025, 8, 3)
        )
        self.assertEqual(
            calls_by_ticker[("AAPL",)]["start_date"], date(2026, 7, 27)
        )
        self.assertTrue(all(
            call["end_date"] == date(2026, 8, 3)
            for call in self.collection_calls
        ))


if __name__ == "__main__":
    unittest.main()
