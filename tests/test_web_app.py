import json
import os
from datetime import date, datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from investment_monitor.application import ConfiguredCollectionResult
from investment_monitor.web import _topbar_summary
from investment_monitor.web import DailyCollectionScheduler, WebApplication
from investment_monitor.models import InformationItem
from investment_monitor.repository import SaveResult
from investment_monitor.sqlite_repository import SQLiteInformationRepository
from investment_monitor.web_repository import WebRepository


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
        # HKEXnews resolution fetches a live stock list; tests keep batch-add
        # paths offline with a stub that resolves nothing.
        class NoOpHkResolver:
            def resolve(self, ticker):
                return None

        self.application.hkexnews_resolver = NoOpHkResolver()

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
            b"This source is not configured",
            b"Request failed",
        ):
            self.assertIn(state_text, script.body)

    def test_bootstrap_uses_fixed_lists_and_truthful_source_status(self) -> None:
        with patch.dict(
            os.environ,
            {"SEC_USER_AGENT": ""},
            clear=False,
        ):
            application = WebApplication(
                self.project_root,
                collection_runner=self.noop_collection_runner,
            )
            response = application.handle("GET", "/api/bootstrap")
            payload = self.payload(response)

        self.assertEqual(response.status, 200)
        self.assertEqual(
            [record["slug"] for record in payload["lists"]],
            ["holdings", "planned", "watchlist"],
        )
        self.assertEqual(payload["sources"][0]["status"], "not_connected")
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

    def test_settings_can_save_and_clear_finnhub_key(self) -> None:
        (self.project_root / "config" / "settings.yaml").write_text(
            "enabled_sources:\n  - sec\n  - news\n"
            "database_path: ../data/web.sqlite3\n",
            encoding="utf-8",
        )
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("FINNHUB_API_KEY", None)
            application = WebApplication(
                self.project_root,
                collection_runner=self.noop_collection_runner,
            )
            saved = self.payload(application.handle(
                "POST",
                "/api/settings",
                json.dumps(
                    {"key": "FINNHUB_API_KEY", "value": "sk-live-1234567890"}
                ).encode(),
            ))
            settings = self.payload(
                application.handle("GET", "/api/settings")
            )
            news = next(
                record
                for record in application.repository.source_statuses()
                if record["type"] == "News"
            )

            self.assertTrue(saved["updated"])
            self.assertTrue(saved["configured"])
            self.assertNotIn("sk-live-1234567890", saved["hint"])
            self.assertEqual(os.environ["FINNHUB_API_KEY"], "sk-live-1234567890")
            news_provider = next(
                provider
                for provider in settings["providers"]
                if provider["name"] == "news"
            )
            news_field = next(
                field
                for field in news_provider["fields"]
                if field["env"] == "FINNHUB_API_KEY"
            )
            self.assertTrue(news_field["configured"])
            self.assertNotIn(
                "sk-live-1234567890",
                json.dumps(settings),
            )
            self.assertEqual(news["status"], "unavailable")
            self.assertIsNone(news["last_failure"])

            cleared = self.payload(application.handle(
                "POST",
                "/api/settings",
                json.dumps({"key": "FINNHUB_API_KEY", "value": ""}).encode(),
            ))
            news = next(
                record
                for record in application.repository.source_statuses()
                if record["type"] == "News"
            )

            self.assertFalse(cleared["configured"])
            self.assertNotIn("FINNHUB_API_KEY", os.environ)
            self.assertEqual(news["status"], "not_connected")
            self.assertIn("FINNHUB_API_KEY", news["last_failure"])

    def test_database_secret_overrides_env_on_startup(self) -> None:
        (self.project_root / "config" / "settings.yaml").write_text(
            "enabled_sources:\n  - sec\n  - news\n"
            "database_path: ../data/web.sqlite3\n",
            encoding="utf-8",
        )
        WebRepository(
            self.project_root / "data" / "web.sqlite3",
            allowed_sources=("sec", "news"),
            allowed_secret_keys=("FINNHUB_API_KEY",),
        ).set_setting("FINNHUB_API_KEY", "db-key-value")
        with patch.dict(
            os.environ,
            {"FINNHUB_API_KEY": "env-key-value"},
            clear=False,
        ):
            application = WebApplication(
                self.project_root,
                collection_runner=self.noop_collection_runner,
            )

            self.assertEqual(os.environ["FINNHUB_API_KEY"], "db-key-value")
            news = next(
                record
                for record in application.repository.source_statuses()
                if record["type"] == "News"
            )
            self.assertEqual(news["status"], "unavailable")

    def test_settings_rejects_non_whitelisted_secret_key(self) -> None:
        response = self.application.handle(
            "POST",
            "/api/settings",
            json.dumps(
                {"key": "AWS_SECRET_ACCESS_KEY", "value": "x"}
            ).encode(),
        )

        self.assertEqual(response.status, 400)

    def test_settings_providers_are_dynamic(self) -> None:
        (self.project_root / "config" / "settings.yaml").write_text(
            "enabled_sources:\n  - sec\n  - news\n  - community\n  - research\n"
            "database_path: ../data/web.sqlite3\n",
            encoding="utf-8",
        )
        application = WebApplication(
            self.project_root,
            collection_runner=self.noop_collection_runner,
        )
        settings = self.payload(
            application.handle("GET", "/api/settings")
        )
        providers = {provider["name"]: provider for provider in settings["providers"]}

        self.assertEqual(
            [field["env"] for field in providers["sec"]["fields"]],
            ["SEC_USER_AGENT"],
        )
        self.assertEqual(
            [field["env"] for field in providers["news"]["fields"]],
            ["FINNHUB_API_KEY"],
        )
        self.assertTrue(providers["sec"]["implemented"])
        self.assertTrue(providers["news"]["implemented"])
        self.assertFalse(providers["community"]["implemented"])
        self.assertFalse(providers["research"]["implemented"])
        self.assertEqual(providers["community"]["fields"], [])
        self.assertTrue(all(
            not field["configured"]
            for provider in providers.values()
            for field in provider["fields"]
        ))

    def test_extra_env_can_be_saved_cleared_and_validated(self) -> None:
        saved = self.payload(self.application.handle(
            "POST",
            "/api/settings",
            json.dumps({"key": "extra_env:MY_APP_TOKEN", "value": "abc123"}).encode(),
        ))
        settings = self.payload(
            self.application.handle("GET", "/api/settings")
        )

        self.assertTrue(saved["configured"])
        self.assertEqual(saved["hint"], "••••c123")
        self.assertEqual(os.environ["MY_APP_TOKEN"], "abc123")
        self.assertEqual(
            settings["extra_env"],
            [{"name": "MY_APP_TOKEN", "configured": True, "hint": "••••c123"}],
        )
        self.assertNotIn("abc123", json.dumps(settings))

        cleared = self.payload(self.application.handle(
            "POST",
            "/api/settings",
            json.dumps({"key": "extra_env:MY_APP_TOKEN", "value": ""}).encode(),
        ))
        settings = self.payload(
            self.application.handle("GET", "/api/settings")
        )
        self.assertFalse(cleared["configured"])
        self.assertNotIn("MY_APP_TOKEN", os.environ)
        self.assertEqual(settings["extra_env"], [])

        for bad_key in ("extra_env:PATH", "extra_env:LD_LIBRARY_PATH", "extra_env:1BAD"):
            response = self.application.handle(
                "POST",
                "/api/settings",
                json.dumps({"key": bad_key, "value": "x"}).encode(),
            )
            self.assertEqual(response.status, 400, bad_key)

    def test_new_source_with_secret_fields_appears_in_provider_catalog(self) -> None:
        from investment_monitor.config import SourceConfig
        from investment_monitor.connectors.base import SecretField
        from investment_monitor.registry import SourceRegistry
        from investment_monitor.web import build_provider_catalog

        class FakeResearchConnector:
            name = "research"
            secret_fields = (
                SecretField(
                    env="RESEARCH_API_KEY",
                    label="Research API Key",
                    help="Research source key.",
                ),
            )

        registry = SourceRegistry()
        registry.register(
            FakeResearchConnector.name,
            FakeResearchConnector,
            secret_fields=FakeResearchConnector.secret_fields,
        )
        catalog = build_provider_catalog(
            registry,
            (
                SourceConfig(
                    name="research",
                    label="Research",
                    source_type="research",
                    enabled=True,
                ),
            ),
        )

        self.assertTrue(catalog[0]["implemented"])
        self.assertEqual(catalog[0]["fields"][0]["env"], "RESEARCH_API_KEY")
        self.assertEqual(catalog[0]["fields"][0]["kind"], "password")

    def test_dart_enabled_without_key_keeps_filings_provider_sec(self) -> None:
        (self.project_root / "config" / "settings.yaml").write_text(
            "enabled_sources:\n  - sec\n  - news\n  - dart\n"
            "database_path: ../data/web.sqlite3\n",
            encoding="utf-8",
        )
        with patch.dict(
            os.environ,
            {"DART_API_KEY": "", "SEC_USER_AGENT": "test-user-agent"},
            clear=False,
        ):
            application = WebApplication(
                self.project_root,
                collection_runner=self.noop_collection_runner,
            )
            settings = self.payload(
                application.handle("GET", "/api/settings")
            )
            statuses = application.repository.source_statuses()

        providers = {
            provider["name"]: provider
            for provider in settings["providers"]
        }
        self.assertTrue(providers["dart"]["implemented"])
        self.assertEqual(
            [field["env"] for field in providers["dart"]["fields"]],
            ["DART_API_KEY"],
        )
        filings = next(
            record for record in statuses if record["type"] == "Filings"
        )
        self.assertEqual(filings["provider"], "SEC EDGAR")

    def test_adding_kr_company_with_dart_cache_maps_corp_code(self) -> None:
        (self.project_root / "config" / "settings.yaml").write_text(
            "enabled_sources:\n  - sec\n  - news\n  - dart\n"
            "database_path: ../data/web.sqlite3\n",
            encoding="utf-8",
        )
        cache_path = (
            self.project_root
            / ".cache"
            / "investment_monitor"
            / "dart_corp_codes.json"
        )
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        cache_path.write_text(
            json.dumps({"005930": ["00593000", "삼성전자"]}),
            encoding="utf-8",
        )
        with patch.dict(
            os.environ,
            {"DART_API_KEY": "test-key"},
            clear=False,
        ):
            application = WebApplication(
                self.project_root,
                collection_runner=self.noop_collection_runner,
            )
            response = application.handle(
                "POST",
                "/api/companies/batch",
                json.dumps(
                    {
                        "tickers": "005930",
                        "lists": ["holdings"],
                        "market": "kr",
                    }
                ).encode(),
            )
            payload = self.payload(response)
            companies = application.repository.companies()

        self.assertEqual(response.status, 201)
        self.assertEqual(payload["added"][0]["market"], "kr")
        self.assertEqual(payload["added"][0]["mapping_status"], "mapped")
        self.assertEqual(payload["added"][0]["cik"], "00593000")
        self.assertEqual(companies[0]["cik"], "00593000")

    def test_adding_kr_company_uses_universe_cache_for_name(self) -> None:
        cache_path = (
            self.project_root
            / ".cache"
            / "investment_monitor"
            / "kr_universe.json"
        )
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        cache_path.write_text(
            json.dumps(
                {
                    "updated_at": "2026-08-05T00:00:00+00:00",
                    "source": "dart_corpcode",
                    "items": [
                        {
                            "stock_code": "005930",
                            "name": "삼성전자",
                            "market_hint": "KRX",
                            "instrument_kind": "equity",
                            "exchange": "KRX",
                        }
                    ],
                }
            ),
            encoding="utf-8",
        )
        with patch.dict(
            os.environ,
            {"KR_UNIVERSE_CACHE_PATH": str(cache_path)},
            clear=False,
        ):
            application = WebApplication(
                self.project_root,
                collection_runner=self.noop_collection_runner,
            )
            response = application.handle(
                "POST",
                "/api/companies/batch",
                json.dumps(
                    {
                        "tickers": "005930",
                        "lists": ["holdings"],
                        "market": "kr",
                    }
                ).encode(),
            )
            payload = self.payload(response)

        self.assertEqual(response.status, 201)
        added = payload["added"][0]
        self.assertEqual(added["name"], "삼성전자")
        self.assertEqual(added["exchange"], "KRX")
        self.assertEqual(added["market"], "kr")
        self.assertEqual(added["mapping_status"], "unmapped")

    def test_adding_uk_company_never_uses_sec_resolver(self) -> None:
        response = self.application.handle(
            "POST",
            "/api/companies/batch",
            json.dumps(
                {
                    "tickers": "MSFT",
                    "lists": ["holdings"],
                    "market": "uk",
                }
            ).encode(),
        )
        payload = self.payload(response)

        self.assertEqual(response.status, 201)
        added = payload["added"][0]
        self.assertEqual(added["ticker"], "MSFT")
        self.assertEqual(added["market"], "uk")
        # MSFT exists in the SEC cache; without the UK guard this would be
        # mapped as the US company.
        self.assertEqual(added["mapping_status"], "unmapped")
        self.assertEqual(added["cik"], "")

    def test_uk_resolver_is_companies_house(self) -> None:
        application = WebApplication(
            self.project_root,
            collection_runner=self.noop_collection_runner,
        )

        self.assertIs(
            application._resolver_for("uk"),
            application.companies_house_resolver,
        )
        self.assertIsNot(
            application._resolver_for("uk"),
            application.resolver,
        )

    def test_adding_hk_company_never_uses_sec_resolver(self) -> None:
        response = self.application.handle(
            "POST",
            "/api/companies/batch",
            json.dumps(
                {
                    "tickers": "MSFT",
                    "lists": ["holdings"],
                    "market": "hk",
                }
            ).encode(),
        )
        payload = self.payload(response)

        self.assertEqual(response.status, 201)
        added = payload["added"][0]
        self.assertEqual(added["ticker"], "MSFT")
        self.assertEqual(added["market"], "hk")
        # MSFT exists in the SEC cache; without the HK guard this would be
        # mapped as the US company.
        self.assertEqual(added["mapping_status"], "unmapped")
        self.assertEqual(added["cik"], "")

    def test_adding_hk_company_uses_universe_cache_for_name(self) -> None:
        cache_path = (
            self.project_root
            / ".cache"
            / "investment_monitor"
            / "hk_universe.json"
        )
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        cache_path.write_text(
            json.dumps(
                {
                    "source": "hkexnews_activestock",
                    "refreshed_at": "2026-08-06T00:00:00+00:00",
                    "entries": {
                        "00700": {
                            "ticker": "00700",
                            "stock_id": "15157",
                            "name": "TENCENT",
                            "name_zh": "騰訊控股",
                            "exchange": "SEHK",
                            "status": "active",
                        }
                    },
                }
            ),
            encoding="utf-8",
        )
        with patch.dict(
            os.environ,
            {"HK_UNIVERSE_CACHE_PATH": str(cache_path)},
            clear=False,
        ):
            application = WebApplication(
                self.project_root,
                collection_runner=self.noop_collection_runner,
            )
            class NoOpHkResolver:
                def resolve(self, ticker):
                    return None

            application.hkexnews_resolver = NoOpHkResolver()
            response = application.handle(
                "POST",
                "/api/companies/batch",
                json.dumps(
                    {
                        "tickers": "00700",
                        "lists": ["holdings"],
                        "market": "hk",
                    }
                ).encode(),
            )
            payload = self.payload(response)

        self.assertEqual(response.status, 201)
        added = payload["added"][0]
        self.assertEqual(added["name"], "TENCENT")
        self.assertEqual(added["exchange"], "SEHK")
        self.assertEqual(added["market"], "hk")
        self.assertEqual(added["mapping_status"], "unmapped")

    def test_hk_resolver_is_hkexnews(self) -> None:
        application = WebApplication(
            self.project_root,
            collection_runner=self.noop_collection_runner,
        )

        self.assertIs(
            application._resolver_for("hk"),
            application.hkexnews_resolver,
        )
        self.assertIsNot(application._resolver_for("hk"), application.resolver)

    def test_tw_resolver_is_none(self) -> None:
        application = WebApplication(
            self.project_root,
            collection_runner=self.noop_collection_runner,
        )

        self.assertIsNone(application._resolver_for("tw"))
        self.assertIsNot(application._resolver_for("tw"), application.resolver)

    def test_adding_tw_company_never_uses_sec_resolver(self) -> None:
        response = self.application.handle(
            "POST",
            "/api/companies/batch",
            json.dumps(
                {
                    "tickers": "MSFT",
                    "lists": ["holdings"],
                    "market": "tw",
                }
            ).encode(),
        )
        payload = self.payload(response)

        self.assertEqual(response.status, 201)
        added = payload["added"][0]
        self.assertEqual(added["ticker"], "MSFT")
        self.assertEqual(added["market"], "tw")
        self.assertEqual(added["mapping_status"], "unmapped")
        self.assertEqual(added["cik"], "")

    def test_ca_resolver_is_none(self) -> None:
        application = WebApplication(
            self.project_root,
            collection_runner=self.noop_collection_runner,
        )

        self.assertIsNone(application._resolver_for("ca"))
        self.assertIsNot(application._resolver_for("ca"), application.resolver)

    def test_adding_ca_company_never_uses_sec_resolver(self) -> None:
        response = self.application.handle(
            "POST",
            "/api/companies/batch",
            json.dumps(
                {
                    "tickers": "RY.TO",
                    "lists": ["holdings"],
                    "market": "ca",
                }
            ).encode(),
        )
        payload = self.payload(response)

        self.assertEqual(response.status, 201)
        added = payload["added"][0]
        self.assertEqual(added["ticker"], "RY")
        self.assertEqual(added["market"], "ca")
        self.assertEqual(added["mapping_status"], "unmapped")
        self.assertEqual(added["cik"], "")

    def test_ca_ticker_input_normalizes_to_root(self) -> None:
        response = self.application.handle(
            "POST",
            "/api/companies/batch",
            json.dumps(
                {
                    "tickers": "RY, RY.TO, ry-TO",
                    "lists": ["holdings"],
                    "market": "ca",
                }
            ).encode(),
        )
        payload = self.payload(response)

        self.assertEqual(response.status, 201)
        self.assertEqual(len(payload["added"]), 1)
        self.assertEqual(payload["added"][0]["ticker"], "RY")
        self.assertEqual(payload["added"][0]["market"], "ca")
        self.assertEqual(payload["added"][0]["mapping_status"], "unmapped")

    def test_adding_ca_company_uses_universe_cache_for_name(self) -> None:
        cache_path = (
            self.project_root
            / ".cache"
            / "investment_monitor"
            / "ca_universe.json"
        )
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        cache_path.write_text(
            json.dumps(
                {
                    "updated_at": "2026-08-08T00:00:00+00:00",
                    "source": ["tsx_directory"],
                    "counts": {"TSX": 1, "TSXV": 0},
                    "items": [
                        {
                            "ticker": "RY",
                            "name": "Royal Bank of Canada",
                            "board": "TSX",
                            "exchange": "TSX",
                            "status": "active",
                        }
                    ],
                }
            ),
            encoding="utf-8",
        )
        with patch.dict(
            os.environ,
            {"CA_UNIVERSE_CACHE_PATH": str(cache_path)},
            clear=False,
        ):
            application = WebApplication(
                self.project_root,
                collection_runner=self.noop_collection_runner,
            )
            response = application.handle(
                "POST",
                "/api/companies/batch",
                json.dumps(
                    {
                        "tickers": "RY.TO",
                        "lists": ["holdings"],
                        "market": "ca",
                    }
                ).encode(),
            )
            payload = self.payload(response)

        self.assertEqual(response.status, 201)
        added = payload["added"][0]
        self.assertEqual(added["ticker"], "RY")
        self.assertEqual(added["name"], "Royal Bank of Canada")
        self.assertEqual(added["exchange"], "TSX")
        self.assertEqual(added["market"], "ca")
        self.assertEqual(added["mapping_status"], "unmapped")

    def test_au_resolver_is_none(self) -> None:
        application = WebApplication(
            self.project_root,
            collection_runner=self.noop_collection_runner,
        )

        self.assertIsNone(application._resolver_for("au"))
        self.assertIsNot(application._resolver_for("au"), application.resolver)

    def test_adding_au_company_never_uses_sec_resolver(self) -> None:
        response = self.application.handle(
            "POST",
            "/api/companies/batch",
            json.dumps(
                {
                    "tickers": "BHP.AX",
                    "lists": ["holdings"],
                    "market": "au",
                }
            ).encode(),
        )
        payload = self.payload(response)

        self.assertEqual(response.status, 201)
        added = payload["added"][0]
        self.assertEqual(added["ticker"], "BHP")
        self.assertEqual(added["market"], "au")
        self.assertEqual(added["mapping_status"], "unmapped")
        self.assertEqual(added["cik"], "")

    def test_hk_ticker_input_normalizes_to_five_digits(self) -> None:
        response = self.application.handle(
            "POST",
            "/api/companies/batch",
            json.dumps(
                {
                    "tickers": "700, 0700.HK",
                    "lists": ["holdings"],
                    "market": "hk",
                }
            ).encode(),
        )
        payload = self.payload(response)

        self.assertEqual(response.status, 201)
        self.assertEqual(len(payload["added"]), 1)
        self.assertEqual(payload["added"][0]["ticker"], "00700")
        self.assertEqual(payload["added"][0]["market"], "hk")
        self.assertEqual(payload["added"][0]["mapping_status"], "unmapped")

    def test_confirm_ch_mapping_promotes_to_mapped(self) -> None:
        class FakeChResolver:
            def confirm(self, ticker, company_number=None):
                return {
                    "ticker": ticker,
                    "name": "EXAMPLE CO PLC",
                    "cik": "01234567",
                    "exchange": "LSE",
                    "mapping_status": "mapped",
                }

        self.application.companies_house_resolver = FakeChResolver()
        self.application.repository.set_company_mapping(
            {
                "ticker": "SOMECO",
                "name": "EXAMPLE CO PLC",
                "exchange": "Unverified",
                "cik": "01234567",
                "mapping_status": "unverified",
            },
            market="uk",
        )

        response = self.application.handle(
            "POST",
            "/api/companies/confirm-mapping",
            json.dumps(
                {
                    "ticker": "SOMECO",
                    "market": "uk",
                    "company_number": "01234567",
                }
            ).encode(),
        )
        payload = self.payload(response)
        companies = {
            company["ticker"]: company
            for company in self.application.repository.companies()
        }

        self.assertEqual(response.status, 200)
        self.assertEqual(payload["mapping_status"], "mapped")
        self.assertEqual(
            companies["SOMECO"]["mapping_status"],
            "mapped",
        )

    def test_confirm_ch_mapping_failure_keeps_unverified(self) -> None:
        class FailingChResolver:
            def confirm(self, ticker, company_number=None):
                return None

        self.application.companies_house_resolver = FailingChResolver()
        self.application.repository.set_company_mapping(
            {
                "ticker": "SOMECO",
                "name": "EXAMPLE CO PLC",
                "exchange": "Unverified",
                "cik": "01234567",
                "mapping_status": "unverified",
            },
            market="uk",
        )

        response = self.application.handle(
            "POST",
            "/api/companies/confirm-mapping",
            json.dumps(
                {
                    "ticker": "SOMECO",
                    "market": "uk",
                    "company_number": "01234567",
                }
            ).encode(),
        )
        payload = self.payload(response)
        companies = {
            company["ticker"]: company
            for company in self.application.repository.companies()
        }

        self.assertEqual(response.status, 409)
        self.assertIn("unverified", payload["error"])
        self.assertEqual(companies["SOMECO"]["mapping_status"], "unverified")

    def test_adding_uk_company_uses_universe_cache_for_name(self) -> None:
        cache_path = (
            self.project_root
            / ".cache"
            / "investment_monitor"
            / "uk_universe.json"
        )
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        cache_path.write_text(
            json.dumps(
                {
                    "updated_at": "2026-08-06T00:00:00+00:00",
                    "source": "firds",
                    "items": [
                        {
                            "ticker": "VOD",
                            "name": "VODAFONE GROUP PUBLIC LIMITED COMPANY",
                            "isin": "GB00BH4HKS39",
                            "exchange": "LSE",
                            "instrument_kind": "equity",
                        }
                    ],
                }
            ),
            encoding="utf-8",
        )
        with patch.dict(
            os.environ,
            {"UK_UNIVERSE_CACHE_PATH": str(cache_path)},
            clear=False,
        ):
            application = WebApplication(
                self.project_root,
                collection_runner=self.noop_collection_runner,
            )
            response = application.handle(
                "POST",
                "/api/companies/batch",
                json.dumps(
                    {
                        "tickers": "VOD",
                        "lists": ["holdings"],
                        "market": "uk",
                    }
                ).encode(),
            )
            payload = self.payload(response)

        self.assertEqual(response.status, 201)
        added = payload["added"][0]
        self.assertEqual(added["ticker"], "VOD")
        self.assertEqual(added["name"], "VODAFONE GROUP PUBLIC LIMITED COMPANY")
        self.assertEqual(added["exchange"], "LSE")
        self.assertEqual(added["mapping_status"], "unmapped")

    def test_bootstrap_list_unread_counts_only_today(self) -> None:
        self.items.save([
            InformationItem(
                source="sec",
                source_type="regulatory_filing",
                external_id="today-1",
                tickers=("AAPL",),
                issuer="Apple Inc.",
                published_at=datetime(2026, 8, 2, tzinfo=timezone.utc),
                title="Today filing",
                document_type="8-K",
                url="https://www.sec.gov/today-1",
                collected_at=datetime(2026, 8, 2, 13, tzinfo=timezone.utc),
                raw_metadata={
                    "acceptanceDateTime": "2026-08-02T12:00:00+00:00"
                },
            ),
            InformationItem(
                source="sec",
                source_type="regulatory_filing",
                external_id="today-2",
                tickers=("AAPL",),
                issuer="Apple Inc.",
                published_at=datetime(2026, 8, 2, tzinfo=timezone.utc),
                title="Today filing two",
                document_type="8-K",
                url="https://www.sec.gov/today-2",
                collected_at=datetime(2026, 8, 2, 13, tzinfo=timezone.utc),
                raw_metadata={
                    "acceptanceDateTime": "2026-08-02T13:00:00+00:00"
                },
            ),
            InformationItem(
                source="sec",
                source_type="regulatory_filing",
                external_id="old-1",
                tickers=("AAPL",),
                issuer="Apple Inc.",
                published_at=datetime(2026, 8, 1, tzinfo=timezone.utc),
                title="Old filing",
                document_type="8-K",
                url="https://www.sec.gov/old-1",
                collected_at=datetime(2026, 8, 1, 13, tzinfo=timezone.utc),
                raw_metadata={
                    "acceptanceDateTime": "2026-08-01T12:00:00+00:00"
                },
            ),
        ])

        payload = self.payload(
            self.application.handle("GET", "/api/bootstrap?date=2026-08-02")
        )

        holdings = next(
            list_record
            for list_record in payload["lists"]
            if list_record["slug"] == "holdings"
        )
        self.assertEqual(holdings["unread_count"], 2)
        self.assertEqual(payload["counts"]["unread"], 2)
        self.assertNotEqual(holdings["unread_count"], 3)

    def test_bootstrap_echoes_user_timezone(self) -> None:
        payload = self.payload(
            self.application.handle(
                "GET",
                "/api/bootstrap?date=2026-08-06&timezone=Asia/Shanghai",
            )
        )

        self.assertEqual(payload["selected_date"], "2026-08-06")
        self.assertEqual(payload["timezone"], "Asia/Shanghai")
        self.assertEqual(payload["timezone_label"], "Asia/Shanghai")

    def test_bootstrap_invalid_timezone_falls_back_safely(self) -> None:
        response = self.application.handle(
            "GET",
            "/api/bootstrap?date=2026-08-06&timezone=Not/AZone",
        )
        payload = self.payload(response)

        self.assertEqual(response.status, 200)
        self.assertEqual(payload["timezone"], "America/New_York")

    def test_feed_accepts_user_timezone(self) -> None:
        response = self.application.handle(
            "GET",
            "/api/feed?start_date=2026-08-06&end_date=2026-08-06"
            "&timezone=Asia/Shanghai",
        )

        self.assertEqual(response.status, 200)

    def test_bootstrap_topbar_summary_uses_multi_source_providers(self) -> None:
        with patch.object(
            self.application.repository,
            "source_statuses",
            return_value=[
                {
                    "type": "Filings",
                    "provider": "OpenDART, KIND (KRX)",
                    "status": "connected",
                },
                {
                    "type": "News",
                    "provider": None,
                    "status": "not_connected",
                },
                {
                    "type": "Community",
                    "provider": None,
                    "status": "not_connected",
                },
                {
                    "type": "Research",
                    "provider": None,
                    "status": "not_connected",
                },
            ],
        ):
            payload = self.payload(
                self.application.handle(
                    "GET",
                    "/api/bootstrap?date=2026-08-06",
                )
            )

        self.assertEqual(
            payload["topbar_summary"],
            {
                "text": "Sources up to date · OpenDART, KIND (KRX)",
                "level": "connected",
            },
        )
        self.assertNotIn("SEC Up to date", payload["topbar_summary"]["text"])

    def test_bootstrap_topbar_summary_mixed_stale(self) -> None:
        with patch.object(
            self.application.repository,
            "source_statuses",
            return_value=[
                {
                    "type": "Filings",
                    "provider": "OpenDART, KIND (KRX)",
                    "status": "connected",
                },
                {
                    "type": "News",
                    "provider": "Naver Finance",
                    "status": "stale",
                },
            ],
        ):
            payload = self.payload(
                self.application.handle(
                    "GET",
                    "/api/bootstrap?date=2026-08-06",
                )
            )

        self.assertEqual(
            payload["topbar_summary"],
            {
                "text": (
                    "Sources: OpenDART, KIND (KRX) up to date"
                    " · Naver Finance stale"
                ),
                "level": "stale",
            },
        )

    def test_bootstrap_topbar_summary_all_down(self) -> None:
        with patch.object(
            self.application.repository,
            "source_statuses",
            return_value=[
                {
                    "type": "Filings",
                    "provider": "OpenDART",
                    "status": "unavailable",
                },
                {
                    "type": "News",
                    "provider": None,
                    "status": "not_connected",
                },
            ],
        ):
            payload = self.payload(
                self.application.handle(
                    "GET",
                    "/api/bootstrap?date=2026-08-06",
                )
            )

        self.assertEqual(
            payload["topbar_summary"],
            {"text": "Sources unavailable / Not connected", "level": "failed"},
        )

    def test_topbar_summary_single_sec_uses_generic_wording(self) -> None:
        summary = _topbar_summary(
            [
                {
                    "type": "Filings",
                    "provider": "SEC EDGAR",
                    "status": "connected",
                },
            ]
        )

        self.assertEqual(
            summary,
            {"text": "Sources up to date · SEC EDGAR", "level": "connected"},
        )
        self.assertNotIn("SEC Up to date", summary["text"])

    def test_app_js_has_no_sec_only_topbar_copy(self) -> None:
        app_js = (
            Path(__file__).resolve().parents[1]
            / "src"
            / "investment_monitor"
            / "web_static"
            / "app.js"
        )
        text = app_js.read_text(encoding="utf-8")

        self.assertNotIn("SEC Up to date", text)
        self.assertNotIn("SEC Data stale", text)
        self.assertNotIn("SEC Unavailable", text)
        self.assertIn("topbar_summary", text)

    def test_page_size_setting_still_works(self) -> None:
        response = self.application.handle(
            "POST",
            "/api/settings",
            json.dumps({"key": "page_size", "value": "50"}).encode(),
        )
        settings = self.payload(
            self.application.handle("GET", "/api/settings")
        )

        self.assertEqual(response.status, 200)
        self.assertEqual(settings["page_size"], 50)

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
