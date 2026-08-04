from datetime import date, datetime, timezone
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory
import unittest

from investment_monitor import (
    CollectionPipeline,
    CollectionRequest,
    InformationItem,
    MARKET_HK,
    MARKET_US,
    SourceRegistry,
    SQLiteInformationRepository,
    WebRepository,
    load_settings,
    load_universe,
    run_ticker_collection,
)
from investment_monitor.web_repository import FeedFilters


def make_item(
    external_id: str,
    *,
    ticker: str = "AAPL",
    market: str = MARKET_US,
    source: str = "sec",
    source_type: str = "regulatory_filing",
    summary: str = None,
    generated: bool = False,
) -> InformationItem:
    return InformationItem(
        source=source,
        source_type=source_type,
        external_id=external_id,
        tickers=(ticker,),
        issuer="Apple Inc." if ticker == "AAPL" else f"{ticker} Issuer",
        published_at=datetime(2026, 8, 2, tzinfo=timezone.utc),
        title=f"Item {external_id}",
        document_type="10-Q" if source == "sec" else "post",
        url=f"https://example.test/{external_id}",
        collected_at=datetime(2026, 8, 2, 13, tzinfo=timezone.utc),
        raw_metadata={"generated": generated},
        market=market,
        summary=summary,
        effective_at=datetime(2026, 8, 2, 12, 45, tzinfo=timezone.utc),
    )


class FakeResolver:
    def resolve(self, ticker: str):
        return {
            "AAPL": {
                "ticker": "AAPL",
                "name": "Apple Inc.",
                "exchange": "Nasdaq",
                "cik": "0000320193",
                "mapping_status": "mapped",
            },
        }.get(ticker)


class InformationModelTests(unittest.TestCase):
    def test_market_is_validated_and_normalized(self) -> None:
        item = make_item("x", market="US")
        self.assertEqual(item.market, "us")
        with self.assertRaises(ValueError):
            make_item("x", market="europe")

    def test_summary_and_effective_time_round_trip_through_sqlite(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            repository = SQLiteInformationRepository(
                Path(temporary_directory) / "items.sqlite3"
            )
            with_summary = make_item(
                "with-summary",
                source="research",
                source_type="research",
                summary="A short research summary.",
            )
            without_summary = make_item("without-summary", source="news", source_type="news")

            repository.save([with_summary, without_summary])
            stored = repository.query()

        by_id = {item.external_id: item for item in stored}
        self.assertEqual(by_id["with-summary"].summary, "A short research summary.")
        self.assertIsNone(by_id["without-summary"].summary)
        self.assertEqual(
            by_id["with-summary"].effective_at,
            datetime(2026, 8, 2, 12, 45, tzinfo=timezone.utc),
        )
        self.assertEqual(by_id["with-summary"].market, "us")

    def test_market_is_carried_on_item_ticker_rows(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            repository = SQLiteInformationRepository(
                Path(temporary_directory) / "items.sqlite3"
            )
            repository.save([make_item("hk-item", market=MARKET_HK)])
            stored = repository.query()[0]

        self.assertEqual(stored.market, "hk")


class MultiMarketCompanyTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = TemporaryDirectory()
        self.database_path = Path(self.temporary_directory.name) / "web.sqlite3"
        self.items = SQLiteInformationRepository(self.database_path)
        self.repository = WebRepository(self.database_path)
        self.resolver = FakeResolver()

    def tearDown(self) -> None:
        self.temporary_directory.cleanup()

    def test_same_ticker_in_different_markets_are_distinct_companies(self) -> None:
        self.repository.add_companies_batch(
            "AAPL", ("holdings",), self.resolver, market=MARKET_US
        )
        self.repository.add_companies_batch(
            "AAPL", ("watchlist",), self.resolver, market=MARKET_HK
        )

        companies = self.repository.companies()

        self.assertEqual(len(companies), 2)
        self.assertEqual(
            {(company["ticker"], company["market"]) for company in companies},
            {("AAPL", "us"), ("AAPL", "hk")},
        )

    def test_feed_and_membership_ops_are_market_scoped(self) -> None:
        self.repository.add_companies_batch(
            "AAPL", ("holdings",), self.resolver, market=MARKET_US
        )
        self.repository.add_companies_batch(
            "AAPL", ("holdings",), self.resolver, market=MARKET_HK
        )
        self.items.save(
            [
                make_item("us-1", market=MARKET_US),
                make_item("hk-1", market=MARKET_HK),
            ]
        )

        feed = self.repository.query_feed(FeedFilters())

        self.assertEqual(
            {(item["ticker"], item["market"]) for item in feed.items},
            {("AAPL", "us"), ("AAPL", "hk")},
        )
        self.assertTrue(self.repository.remove_membership("AAPL", "holdings", MARKET_HK))
        remaining = self.repository.query_feed(FeedFilters())
        self.assertEqual(
            {(item["external_id"], item["market"]) for item in remaining.items},
            {("us-1", "us")},
        )
        self.assertEqual(self.repository.remove_all_memberships("AAPL", MARKET_HK), 0)

    def test_legacy_database_is_upgraded_without_losing_sec_rows(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            database_path = Path(temporary_directory) / "legacy.sqlite3"
            connection = sqlite3.connect(str(database_path))
            try:
                connection.executescript(
                    """
                    CREATE TABLE information_items (
                        id INTEGER PRIMARY KEY,
                        source TEXT NOT NULL,
                        source_type TEXT NOT NULL,
                        external_id TEXT NOT NULL,
                        issuer TEXT NOT NULL,
                        published_at TEXT NOT NULL,
                        title TEXT NOT NULL,
                        document_type TEXT NOT NULL,
                        url TEXT NOT NULL,
                        collected_at TEXT NOT NULL,
                        raw_metadata TEXT NOT NULL,
                        UNIQUE (source, external_id)
                    );
                    CREATE TABLE information_item_tickers (
                        item_id INTEGER NOT NULL,
                        ticker TEXT NOT NULL,
                        PRIMARY KEY (item_id, ticker),
                        FOREIGN KEY (item_id)
                            REFERENCES information_items(id) ON DELETE CASCADE
                    );
                    CREATE TABLE companies (
                        id INTEGER PRIMARY KEY,
                        ticker TEXT NOT NULL UNIQUE,
                        name TEXT NOT NULL,
                        exchange TEXT,
                        cik TEXT,
                        mapping_status TEXT NOT NULL DEFAULT 'mapped',
                        created_at TEXT NOT NULL,
                        updated_at TEXT NOT NULL
                    );
                    INSERT INTO information_items (
                        source, source_type, external_id, issuer, published_at,
                        title, document_type, url, collected_at, raw_metadata
                    ) VALUES (
                        'sec', 'regulatory_filing', 'legacy-1', 'Apple Inc.',
                        '2026-01-10T00:00:00+00:00', 'Legacy 10-Q', '10-Q',
                        'https://www.sec.gov/legacy', '2026-01-11T00:00:00+00:00',
                        '{"cik": "0000320193"}'
                    );
                    INSERT INTO information_item_tickers (item_id, ticker)
                    VALUES (1, 'AAPL');
                    INSERT INTO companies (
                        ticker, name, exchange, cik, mapping_status,
                        created_at, updated_at
                    ) VALUES (
                        'AAPL', 'Apple Inc.', 'Nasdaq', '0000320193', 'mapped',
                        '2026-01-01T00:00:00+00:00', '2026-01-01T00:00:00+00:00'
                    );
                    """
                )
            finally:
                connection.close()

            repository = WebRepository(database_path)
            repository.add_companies_batch(
                "AAPL", ("holdings",), self.resolver, market=MARKET_US
            )
            repository.add_companies_batch(
                "AAPL", ("planned",), self.resolver, market=MARKET_HK
            )
            stored = SQLiteInformationRepository(database_path).query(source="sec")

            self.assertEqual(stored[0].external_id, "legacy-1")
            self.assertEqual(stored[0].market, "us")
            companies = {
                (company["ticker"], company["market"])
                for company in repository.companies()
            }
            self.assertEqual(companies, {("AAPL", "us"), ("AAPL", "hk")})

    def test_non_us_company_can_be_added_without_sec_mapping(self) -> None:
        result = self.repository.add_companies_batch(
            "0700.HK",
            ("holdings",),
            self.resolver,
            market="hk",
        )

        self.assertEqual(len(result["added"]), 1)
        self.assertEqual(result["failed"], [])
        added = result["added"][0]
        self.assertEqual(added["ticker"], "0700.HK")
        self.assertEqual(added["market"], "hk")
        self.assertEqual(added["mapping_status"], "unmapped")
        self.assertEqual(self.repository.companies()[0]["cik"], "")

    def test_us_ticker_still_requires_sec_mapping(self) -> None:
        result = self.repository.add_companies_batch(
            "BADTICKER",
            ("holdings",),
            self.resolver,
            market="us",
        )

        self.assertEqual(result["added"], [])
        self.assertEqual(result["failed"][0]["ticker"], "BADTICKER")


class SourceStatusAndFilterTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = TemporaryDirectory()
        self.database_path = Path(self.temporary_directory.name) / "web.sqlite3"
        self.items = SQLiteInformationRepository(self.database_path)
        self.repository = WebRepository(self.database_path)
        self.resolver = FakeResolver()

    def tearDown(self) -> None:
        self.temporary_directory.cleanup()

    def test_research_placeholder_and_feed_empty_state(self) -> None:
        self.repository.add_companies_batch(
            "AAPL", ("holdings",), self.resolver, market=MARKET_US
        )

        statuses = {
            record["type"]: record for record in self.repository.source_statuses()
        }
        research = self.repository.query_feed(
            FeedFilters(information_type="research")
        )

        self.assertEqual(statuses["Research"]["status"], "not_connected")
        self.assertEqual(statuses["News"]["status"], "not_connected")
        self.assertEqual(statuses["Community"]["status"], "not_connected")
        self.assertEqual(research.total, 0)

    def test_summary_is_exposed_on_feed_items_when_present(self) -> None:
        self.repository.add_companies_batch(
            "AAPL", ("holdings",), self.resolver, market=MARKET_US
        )
        self.items.save(
            [
                make_item("with-summary", source="research", source_type="research",
                          summary="Research summary text."),
                make_item("no-summary", source="research", source_type="research"),
            ]
        )
        production = WebRepository(
            self.database_path,
            allowed_sources=("sec", "research"),
            implemented_sources=("sec", "research"),
        )

        feed = production.query_feed(FeedFilters())
        by_id = {item["external_id"]: item for item in feed.items}

        self.assertEqual(by_id["with-summary"]["summary"], "Research summary text.")
        self.assertIsNone(by_id["no-summary"]["summary"])
        self.assertEqual(by_id["with-summary"]["source_label"], "Research")

    def test_backfill_selection_considers_all_enabled_sources(self) -> None:
        self.repository.add_companies_batch(
            "AAPL", ("holdings",), self.resolver, market=MARKET_US
        )
        self.items.save([make_item("apple-sec")])

        backfill = self.repository.active_companies_without_any_source_items(
            ("sec", "news")
        )

        # AAPL already has SEC data, so no source needs a full backfill.
        self.assertEqual(backfill, ())
        self.assertEqual(
            self.repository.active_companies_without_source_items("news"),
            (("AAPL", "us"),),
        )

    def test_registry_skips_unimplemented_enabled_sources(self) -> None:
        registry = SourceRegistry()
        missing: list = []

        connectors = registry.load_enabled(["news"], missing=missing)

        self.assertEqual(connectors, [])
        self.assertEqual(missing, ["news"])

    def test_enabled_unimplemented_source_does_not_crash_or_write_fake_data(
        self,
    ) -> None:
        with TemporaryDirectory() as temporary_directory:
            directory = Path(temporary_directory)
            settings_path = directory / "settings.yaml"
            settings_path.write_text(
                "enabled_sources:\n"
                "  - news\n"
                "database_path: data/items.sqlite3\n",
                encoding="utf-8",
            )

            result = run_ticker_collection(
                tickers=("AAPL",),
                settings_path=settings_path,
                start_date=date(2026, 8, 1),
                end_date=date(2026, 8, 2),
            )

            self.assertEqual(result.items, ())
            self.assertEqual(result.failures, ())
            self.assertEqual(result.stored_count, 0)
            self.assertEqual(result.save_result.inserted, 0)


class ConfigFormatTests(unittest.TestCase):
    def test_settings_declares_logical_sources_with_enabled_flags(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            directory = Path(temporary_directory)
            settings_path = directory / "settings.yaml"
            settings_path.write_text(
                "database_path: data/items.sqlite3\n"
                "sources:\n"
                "  - name: sec\n"
                "    label: SEC EDGAR\n"
                "    source_type: filings\n"
                "    enabled: true\n"
                "  - name: news\n"
                "    label: News\n"
                "    source_type: news\n"
                "    enabled: false\n"
                "  - name: research\n"
                "    label: Research\n"
                "    source_type: research\n"
                "    enabled: false\n",
                encoding="utf-8",
            )

            settings = load_settings(settings_path)

        self.assertEqual(settings.enabled_sources, ("sec",))
        self.assertEqual(
            [source.name for source in settings.sources],
            ["sec", "news", "research"],
        )
        self.assertEqual(settings.sources[1].source_type, "news")

    def test_universe_csv_accepts_market_and_allows_repeated_ticker(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            universe_path = Path(temporary_directory) / "universe.csv"
            universe_path.write_text(
                "ticker,list_type,market\n"
                "AAPL,holdings,us\n"
                "AAPL,planned,hk\n"
                "0700.HK,watchlist,hk\n",
                encoding="utf-8",
            )

            universe = load_universe(universe_path)

        self.assertEqual(
            [(entry.ticker, entry.market) for entry in universe],
            [("AAPL", "us"), ("AAPL", "hk"), ("0700.HK", "hk")],
        )

    def test_universe_csv_rejects_unknown_market(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            universe_path = Path(temporary_directory) / "universe.csv"
            universe_path.write_text(
                "ticker,list_type,market\nAAPL,holdings,mars\n",
                encoding="utf-8",
            )
            from investment_monitor import ConfigurationError

            with self.assertRaisesRegex(ConfigurationError, "market"):
                load_universe(universe_path)


class MarketAwarePipelineTests(unittest.TestCase):
    def test_pipeline_forwards_each_ticker_market_to_the_connector(self) -> None:
        seen_markets = []

        class MarketAwareConnector:
            name = "research"

            def collect(self, request: CollectionRequest):
                seen_markets.append(request.market_for(request.tickers[0]))
                return []

        pipeline = CollectionPipeline([MarketAwareConnector()])
        pipeline.collect(
            CollectionRequest(
                tickers=("AAPL", "0700.HK"),
                start_date=date(2026, 8, 1),
                end_date=date(2026, 8, 2),
                markets={"AAPL": "us", "0700.HK": "hk"},
            )
        )

        self.assertEqual(seen_markets, ["us", "hk"])


if __name__ == "__main__":
    unittest.main()
