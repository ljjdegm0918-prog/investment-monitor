import json
import os
import time
from datetime import date, datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from investment_monitor.application import ConfiguredCollectionResult
from investment_monitor.pipeline import CollectionFailure
from investment_monitor.web import DailyCollectionScheduler, WebApplication
from investment_monitor.models import InformationItem
from investment_monitor.repository import SaveResult
from investment_monitor.sqlite_repository import SQLiteInformationRepository
from investment_monitor.web_repository import WebRepository


class _NoneResolver:
    """A resolver that never maps a ticker (non-US markets stay unmapped)."""

    def resolve(self, ticker):
        return None


class _RecordingResolver:
    """A resolver that records every ticker it is asked to resolve."""

    def __init__(self):
        self.calls = []

    def resolve(self, ticker):
        self.calls.append(ticker)
        return None


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
        # stored_count=0 避免后台线程触碰 SQLite：异步回填的 daemon 线程可能在
        # tearDown 删除临时目录时才跑，这里不做任何 DB IO 以免 Windows 文件锁。
        return ConfiguredCollectionResult(
            items=(),
            failures=(),
            save_result=SaveResult(),
            database_path=self.project_root / "data" / "web.sqlite3",
            stored_count=0,
        )

    def test_core_pages_and_static_assets_are_served(self) -> None:
        page = self.application.handle("GET", "/today")
        legacy_information = self.application.handle("GET", "/information")
        legacy_sources = self.application.handle("GET", "/sources")
        script = self.application.handle("GET", "/static/app.js")
        favicon = self.application.handle("GET", "/favicon.ico")

        self.assertEqual(page.status, 200)
        self.assertIn(b"Investment Monitor", page.body)
        self.assertIn(b'data-view="today"', page.body)
        self.assertIn(b'data-view="today"', legacy_information.body)
        self.assertIn(b'data-view="manage"', legacy_sources.body)
        self.assertEqual(script.status, 200)
        self.assertEqual(favicon.status, 204)
        self.assertIn(b'target="_blank" rel="noopener noreferrer"', script.body)
        self.assertIn(b"function renderFatal", script.body)
        for state_text in (
            b"Loading information",
            b"No information for this date",
            b"Search returned no results",
            b"Information sources",
            b"Request failed",
        ):
            self.assertIn(state_text, script.body)

    def test_p0_list_company_search_daily_and_source_workflow(self) -> None:
        manage = self.application.handle("GET", "/manage")
        created = self.payload(self.application.handle(
            "POST", "/api/lists", json.dumps({"name": "Long Term"}).encode()
        ))
        slug = created["list"]["slug"]
        renamed = self.payload(self.application.handle(
            "POST", "/api/lists/rename",
            json.dumps({"slug": slug, "name": "Long Term Quality"}).encode(),
        ))
        candidates = self.payload(self.application.handle(
            "GET", "/api/companies/search?q=Apple"
        ))
        added = self.application.handle(
            "POST", "/api/companies/batch",
            json.dumps({"tickers": "AAPL", "lists": [slug], "market": "us"}).encode(),
        )
        self.items.save((InformationItem(
            source="sec",
            source_type="regulatory_filing",
            external_id="daily-aapl",
            tickers=("AAPL",),
            issuer="Apple Inc.",
            published_at=datetime(2026, 8, 2, 15, tzinfo=timezone.utc),
            title="Apple daily filing",
            document_type="8-K",
            url="https://www.sec.gov/Archives/daily-aapl.htm",
            collected_at=datetime(2026, 8, 2, 16, tzinfo=timezone.utc),
            raw_metadata={"acceptanceDateTime": "2026-08-02T11:00:00-04:00"},
        ),))
        daily = self.payload(self.application.handle(
            "GET", f"/api/daily?date=2026-08-02&list={slug}"
        ))
        sources = self.payload(self.application.handle("GET", "/api/sources"))

        self.assertEqual(manage.status, 200)
        self.assertEqual(renamed["list"]["name"], "Long Term Quality")
        self.assertEqual(candidates["candidates"][0]["ticker"], "AAPL")
        self.assertEqual(added.status, 201)
        self.assertEqual(daily["companies"][0]["name"], "Apple Inc.")
        self.assertEqual(
            set(daily["companies"][0]["items"][0]),
            {"time", "type", "source", "title", "url", "also_seen_on"},
        )
        self.assertEqual(daily["companies"][0]["items"][0]["type"], "Filing")
        sec = next(source for source in sources["sources"] if source["name"] == "sec")
        self.assertEqual(sec["regions"], ["United States"])

        deleted = self.application.handle(
            "POST", "/api/lists/delete", json.dumps({"slug": slug}).encode()
        )
        self.assertEqual(deleted.status, 200)

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

    def test_cold_supported_universe_refreshes_and_backfills_first_add(self) -> None:
        cases = (
            ("de", "SAP", "SAP SE", "Xetra", "de"),
            ("nl", "ASML", "ASML Holding NV", "Euronext Amsterdam", "nl"),
            ("it", "ENI", "Eni SpA", "Euronext Milan", "it"),
            ("be", "ABI", "Anheuser-Busch InBev SA/NV", "Euronext Brussels", "be"),
            ("pl", "PKO", "PKO Bank Polski SA", "GPW Main Market", "pl"),
        )
        for market, ticker, name, exchange, module_name in cases:
            with self.subTest(market=market):
                fallback = {
                    ticker: {
                        "name": name,
                        "exchange": exchange,
                        "board": exchange,
                        "isin": f"TEST-{market.upper()}-{ticker}",
                    }
                }
                with patch(
                    f"investment_monitor.web.{module_name}_universe_name_map",
                    side_effect=({}, fallback),
                ) as load_mock, patch(
                    f"investment_monitor.web.refresh_{module_name}_universe"
                ) as refresh_mock:
                    response = self.application.handle(
                        "POST",
                        "/api/companies/batch",
                        json.dumps(
                            {
                                "tickers": ticker,
                                "lists": ["holdings"],
                                "market": market,
                            }
                        ).encode(),
                    )
                    payload = self.payload(response)

                self.assertEqual(response.status, 201)
                self.assertEqual(payload["added"][0]["name"], name)
                self.assertEqual(payload["added"][0]["exchange"], exchange)
                refresh_mock.assert_called_once_with()
                self.assertEqual(load_mock.call_count, 2)

    def test_failed_supported_universe_refresh_degrades_to_unmapped_add(self) -> None:
        cases = (
            ("de", "SAP"),
            ("nl", "ASML"),
            ("it", "ENI"),
            ("be", "ABI"),
            ("pl", "PKO"),
        )
        for market, ticker in cases:
            with self.subTest(market=market):
                with patch(
                    f"investment_monitor.web.{market}_universe_name_map",
                    return_value={},
                ) as load_mock, patch(
                    f"investment_monitor.web.refresh_{market}_universe",
                    side_effect=RuntimeError("synthetic universe outage"),
                ) as refresh_mock:
                    with self.assertLogs(
                        "investment_monitor.web", level="WARNING"
                    ) as captured_logs:
                        response = self.application.handle(
                            "POST",
                            "/api/companies/batch",
                            json.dumps(
                                {
                                    "tickers": ticker,
                                    "lists": ["planned"],
                                    "market": market,
                                }
                            ).encode(),
                        )
                    payload = self.payload(response)

                self.assertEqual(response.status, 201)
                self.assertEqual(payload["added"][0]["ticker"], ticker)
                self.assertEqual(payload["added"][0]["mapping_status"], "unmapped")
                refresh_mock.assert_called_once_with()
                self.assertEqual(load_mock.call_count, 2)
                self.assertIn(
                    f"{market}_universe refresh failed on add-company",
                    "\n".join(captured_logs.output),
                )

    def test_es_add_skips_slow_synchronous_universe_refresh(self) -> None:
        with patch(
            "investment_monitor.web.es_universe_name_map",
            return_value={},
        ), patch(
            "investment_monitor.universe.es_universe.refresh_es_universe"
        ) as refresh_mock:
            with self.assertLogs(
                "investment_monitor.web", level="WARNING"
            ) as captured_logs:
                response = self.application.handle(
                    "POST",
                    "/api/companies/batch",
                    json.dumps(
                        {
                            "tickers": "SAN",
                            "lists": ["holdings"],
                            "market": "es",
                        }
                    ).encode(),
                )

        self.assertEqual(response.status, 201)
        refresh_mock.assert_not_called()
        self.assertIn(
            "synchronous refresh skipped",
            "\n".join(captured_logs.output),
        )

    def test_boundary_stub_markets_never_attempt_universe_refresh_on_add(self) -> None:
        cases = (
            ("sg", "D05"),
            ("ch", "NESN"),
            ("se", "ERIC-B"),
        )
        for market, ticker in cases:
            with self.subTest(market=market):
                with patch(
                    f"investment_monitor.web.{market}_universe_name_map",
                    return_value={},
                ), patch(
                    f"investment_monitor.universe.{market}_universe."
                    f"refresh_{market}_universe"
                ) as refresh_mock:
                    response = self.application.handle(
                        "POST",
                        "/api/companies/batch",
                        json.dumps(
                            {
                                "tickers": ticker,
                                "lists": ["holdings"],
                                "market": market,
                            }
                        ).encode(),
                    )

                self.assertEqual(response.status, 201)
                refresh_mock.assert_not_called()

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
    def test_batch_add_mixed_markets_single_request(self) -> None:
        with patch.object(self.application, "hkexnews_resolver", _NoneResolver()), \
             patch.object(self.application, "dart_resolver", _NoneResolver()):
            response = self.application.handle(
                "POST",
                "/api/companies/batch",
                json.dumps({
                    "tickers": "AAPL.US 0700.HK 005930.KR RY.TO",
                    "lists": ["watchlist"],
                    "market": "us",
                }).encode(),
            )
        self.assertEqual(response.status, 201)
        payload = self.payload(response)
        added_by_key = {(record["ticker"], record["market"]) for record in payload["added"]}
        self.assertEqual(len(payload["added"]), 4)
        self.assertEqual(
            added_by_key,
            {("AAPL", "us"), ("00700", "hk"), ("005930", "kr"), ("RY", "ca")},
        )
        # None of the explicit-suffix tokens were forced into the default us.
        self.assertEqual(
            {group["market"] for group in payload["groups"]},
            {"us", "hk", "kr", "ca"},
        )
        # Every added company landed in the requested list.
        companies = self.application.repository.companies()
        for record in payload["added"]:
            self.assertIn("watchlist", [
                c["list_slugs"] for c in companies
                if c["ticker"] == record["ticker"] and c["market"] == record["market"]
            ][0])

    def test_batch_add_at_suffix_format(self) -> None:
        with patch.object(self.application, "hkexnews_resolver", _NoneResolver()), \
             patch.object(self.application, "dart_resolver", _NoneResolver()):
            response = self.application.handle(
                "POST",
                "/api/companies/batch",
                json.dumps({
                    "tickers": "AAPL@US 0700@HK 005930@KR RY@TO",
                    "lists": ["watchlist"],
                    "market": "us",
                }).encode(),
            )
        self.assertEqual(response.status, 201)
        payload = self.payload(response)
        added_by_key = {(record["ticker"], record["market"]) for record in payload["added"]}
        self.assertEqual(
            added_by_key,
            {("AAPL", "us"), ("00700", "hk"), ("005930", "kr"), ("RY", "ca")},
        )
        # The @ suffix is recorded exactly like the dot suffix.
        self.assertEqual(
            {parsed["explicit_suffix"] for parsed in payload["parsed"]},
            {"us", "hk", "kr", "to"},
        )
        # @ and . are interchangeable for the same ticker + market.
        self.assertEqual(
            {group["market"] for group in payload["groups"]},
            {"us", "hk", "kr", "ca"},
        )

    def test_batch_add_same_ticker_two_markets(self) -> None:
        with patch.object(self.application, "hkexnews_resolver", _NoneResolver()):
            response = self.application.handle(
                "POST",
                "/api/companies/batch",
                json.dumps({
                    "tickers": "AAPL.US AAPL.HK",
                    "lists": ["planned"],
                    "market": "us",
                }).encode(),
            )
        self.assertEqual(response.status, 201)
        payload = self.payload(response)
        added_by_key = {(record["ticker"], record["market"]) for record in payload["added"]}
        self.assertEqual(added_by_key, {("AAPL", "us"), ("AAPL", "hk")})
        companies = self.application.repository.companies()
        self.assertEqual(
            {(c["ticker"], c["market"]) for c in companies if c["ticker"] == "AAPL"},
            {("AAPL", "us"), ("AAPL", "hk")},
        )

    def test_batch_add_brk_b_keeps_internal_dot(self) -> None:
        resolver = _RecordingResolver()
        with patch.object(self.application, "resolver", resolver):
            response = self.application.handle(
                "POST",
                "/api/companies/batch",
                json.dumps({
                    "tickers": "BRK.B",
                    "lists": ["holdings"],
                    "market": "us",
                }).encode(),
            )
        self.assertEqual(response.status, 201)
        payload = self.payload(response)
        # The resolver saw the whole "BRK.B", never "BRK" with a market "b".
        self.assertEqual(resolver.calls, ["BRK.B"])
        self.assertEqual(payload["parsed"][0]["ticker"], "BRK.B")
        self.assertEqual(payload["parsed"][0]["market"], "us")
        self.assertIsNone(payload["parsed"][0]["explicit_suffix"])

    def test_batch_add_partial_success(self) -> None:
        with patch.object(self.application, "hkexnews_resolver", _NoneResolver()):
            response = self.application.handle(
                "POST",
                "/api/companies/batch",
                json.dumps({
                    "tickers": "AAPL.US 0700.HK BAD.XYZ",
                    "lists": ["planned"],
                    "market": "us",
                }).encode(),
            )
        self.assertEqual(response.status, 201)
        payload = self.payload(response)
        added_by_key = {(record["ticker"], record["market"]) for record in payload["added"]}
        self.assertIn(("AAPL", "us"), added_by_key)
        self.assertIn(("00700", "hk"), added_by_key)
        # BAD.XYZ is kept as a whole ticker (not "BAD") and fails readably via
        # the existing US resolver path, without blocking the valid tokens.
        self.assertTrue(any(f["ticker"] == "BAD.XYZ" for f in payload["failed"]))
        for failure in payload["failed"]:
            self.assertNotIn("Traceback", failure["error"])
            self.assertNotIn("SECCompanyResolver", failure["error"])

    def test_batch_add_rejects_cross_origin(self) -> None:
        headers = {
            "Content-Type": "application/json",
            "Host": "127.0.0.1:8765",
            "Origin": "https://evil.example.com",
        }
        response = self.application.handle(
            "POST",
            "/api/companies/batch",
            json.dumps({"tickers": "AAPL", "lists": ["holdings"]}).encode(),
            headers=headers,
        )
        self.assertEqual(response.status, 403)

    def test_batch_add_invalid_default_market_rejected(self) -> None:
        response = self.application.handle(
            "POST",
            "/api/companies/batch",
            json.dumps({"tickers": "AAPL", "lists": ["holdings"], "market": "mars"}).encode(),
        )
        self.assertEqual(response.status, 400)
        self.assertIn("market", self.payload(response)["error"])


    def test_csv_import_preserves_all_declared_markets_and_routes_sources(self) -> None:
        (self.project_root / "config" / "settings.yaml").write_text(
            "enabled_sources:\n"
            "  - yahoo_jp\n"
            "  - yahoo_ca\n"
            "  - asx_announcements\n"
            "  - xueqiu\n"
            "database_path: ../data/web.sqlite3\n",
            encoding="utf-8",
        )
        application = WebApplication(
            self.project_root,
            collection_runner=self.noop_collection_runner,
        )
        with patch(
            "investment_monitor.web.ca_universe_name_map",
            return_value={"RY": {"name": "Royal Bank", "exchange": "TSX"}},
        ):
            response = application.handle(
                "POST",
                "/api/companies/csv",
                json.dumps({
                    "csv": (
                        "ticker,market,list\n"
                        "7203,Japan,watchlist\n"
                        "RY.TO,Canada,Planned Purchases\n"
                        "BHP.AX,Australia,holdings\n"
                        "600519,China,watchlist\n"
                    )
                }).encode(),
            )
        payload = self.payload(response)

        self.assertEqual(response.status, 201)
        # 新基底 CSV 导入复用秒回 batch：每个市场组一个后台回填任务。
        # 轮询内存任务直到全部终态后再断言采集参数，避免 daemon 线程竞态。
        deadline = time.monotonic() + 5.0
        while time.monotonic() < deadline and application._backfill_tasks:
            if all(
                task["status"] in ("success", "partial", "failure")
                for task in application._backfill_tasks.values()
            ):
                break
            time.sleep(0.02)

        self.assertEqual(
            {(row["ticker"], row["market"]) for row in payload["added"]},
            {("7203", "jp"), ("RY", "ca"), ("BHP", "au"), ("600519", "cn")},
        )
        self.assertNotIn("unknown", {row["market"] for row in payload["added"]})
        self.assertEqual(
            {call["sources"] for call in self.collection_calls},
            {("yahoo_jp",), ("yahoo_ca",), ("asx_announcements",), ("xueqiu",)},
        )
        self.assertTrue(all(call["initial_backfill"] for call in self.collection_calls))

    def test_csv_import_accepts_custom_list_name_and_reports_invalid_market(self) -> None:
        custom = self.application.repository.create_list("High Conviction")
        response = self.application.handle(
            "POST",
            "/api/companies/csv",
            json.dumps({
                "csv": (
                    "ticker\tmarket\tlist\n"
                    "7203\tJP\tHigh Conviction\n"
                    "SAP\tZZ\tholdings\n"
                )
            }).encode(),
        )
        payload = self.payload(response)

        self.assertEqual(response.status, 201)
        self.assertEqual(payload["added"][0]["market"], "jp")
        self.assertEqual(payload["failed"][0]["row"], 3)
        self.assertIn("Market must be one of", payload["failed"][0]["error"])
        company = next(
            row
            for row in self.application.repository.companies()
            if row["ticker"] == "7203"
        )
        self.assertIn(custom["slug"], company["list_slugs"])

    def test_non_us_markets_never_fall_through_to_sec_resolver(self) -> None:
        for market in ("jp", "cn", "fr", "sg", "se"):
            with self.subTest(market=market):
                self.assertIsNone(self.application._resolver_for(market))
        self.assertIs(self.application._resolver_for("us"), self.application.resolver)
        self.assertIs(
            self.application._resolver_for("unknown"),
            self.application.resolver,
        )

    def test_adding_nvda_backfills_sec_items_in_background(self) -> None:
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

        self.assertEqual(response.status, 201)
        self.assertIsNone(payload["collection"])
        self.assertTrue(payload["backfill_task_id"].startswith("bf-"))
        self.assertEqual(payload["backfill_status"], "queued")

        # 回填在后台线程执行；轮询任务直到终态后再断言落库与采集参数。
        task_id = payload["backfill_task_id"]
        deadline = time.monotonic() + 5.0
        terminal = None
        while time.monotonic() < deadline:
            task = self.payload(application.handle(
                "GET", f"/api/backfill-tasks/{task_id}"
            ))
            if task["status"] in ("success", "partial", "failure"):
                terminal = task
                break
            time.sleep(0.02)
        self.assertIsNotNone(terminal, "backfill task never reached a terminal state")
        self.assertEqual(terminal["status"], "success")
        self.assertIsNone(terminal["error"])

        feed = self.payload(application.handle("GET", "/api/feed?ticker=NVDA"))
        self.assertEqual(feed["pagination"]["total"], 1)
        self.assertEqual(feed["items"][0]["external_id"], "0001045810-26-000060")
        self.assertEqual(self.collection_calls[-1]["tickers"], ("NVDA",))
        self.assertEqual(
            (self.collection_calls[-1]["end_date"] - self.collection_calls[-1]["start_date"]).days,
            30,
        )

    def test_collection_with_items_and_failures_is_partial_and_keeps_source(self) -> None:
        item = InformationItem(
            source="yahoo_de",
            source_type="news",
            external_id="sap-news-1",
            tickers=("SAP",),
            issuer="SAP SE",
            published_at=datetime(2026, 8, 10, tzinfo=timezone.utc),
            title="SAP publishes an update",
            document_type="news",
            url="https://example.test/sap-news-1",
            collected_at=datetime(2026, 8, 10, tzinfo=timezone.utc),
            raw_metadata={},
            market="de",
        )

        def partial_runner(**kwargs):
            return ConfiguredCollectionResult(
                items=(item,),
                failures=(CollectionFailure(
                    source="eqs_dgap",
                    ticker="SAP",
                    message="no_universe_isin",
                ),),
                save_result=SaveResult(inserted=1),
                database_path=self.project_root / "data" / "web.sqlite3",
                stored_count=1,
            )

        application = WebApplication(
            self.project_root,
            collection_runner=partial_runner,
        )

        result = application.collect_tickers(
            ("SAP",),
            lookback_days=30,
            markets={"SAP": "de"},
        )

        self.assertEqual(result["status"], "partial")
        self.assertEqual(result["records_fetched"], 1)
        self.assertEqual(result["failures"], [{
            "source": "eqs_dgap",
            "ticker": "SAP",
            "message": "no_universe_isin",
        }])

    def test_collection_without_items_and_any_failure_is_failure(self) -> None:
        def failed_runner(**kwargs):
            return ConfiguredCollectionResult(
                items=(),
                failures=(CollectionFailure(
                    source="eqs_dgap",
                    ticker="SAP",
                    message="no_universe_isin",
                ),),
                save_result=SaveResult(),
                database_path=self.project_root / "data" / "web.sqlite3",
                stored_count=0,
            )

        application = WebApplication(
            self.project_root,
            collection_runner=failed_runner,
        )

        result = application.collect_tickers(
            ("SAP", "ASML"),
            lookback_days=30,
            markets={"SAP": "de", "ASML": "nl"},
        )

        self.assertEqual(result["status"], "failure")
        self.assertEqual(result["records_fetched"], 0)
        self.assertEqual(result["failures"][0]["source"], "eqs_dgap")

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
        # Ordinary scheduling is always incremental, including pending legacy
        # state; it must not silently turn missing state into a 365-day call.
        collected_tickers = [
            ticker
            for call in self.collection_calls
            for ticker in call["tickers"]
        ]
        self.assertEqual(sorted(collected_tickers), ["AAPL", "NVDA"])
        for call in self.collection_calls:
            self.assertEqual(call["sources"], ("sec",))
            self.assertFalse(call["initial_backfill"])
            self.assertEqual(call["start_date"], date(2026, 7, 27))
            self.assertEqual(call["end_date"], date(2026, 8, 3))


if __name__ == "__main__":
    unittest.main()
