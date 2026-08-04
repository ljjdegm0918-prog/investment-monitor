import json
from datetime import date, datetime, timezone
import os
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch
from urllib.error import HTTPError

from investment_monitor import (
    CollectionPipeline,
    CollectionRequest,
    ConnectorUnavailableError,
    FinnhubClient,
    FinnhubNewsConnector,
    FinnhubNewsRequestError,
    InformationItem,
    SourceRegistry,
    SQLiteInformationRepository,
    WebRepository,
    run_ticker_collection,
)
from investment_monitor.web_repository import FeedFilters


def article(
    *,
    article_id: int = 100,
    headline: str = "Apple announces new product",
    url: str = "https://news.example.test/apple",
    published: datetime = datetime(2026, 8, 1, 12, tzinfo=timezone.utc),
    summary: str = "A short summary.",
) -> dict:
    return {
        "category": "company",
        "datetime": int(published.timestamp()),
        "headline": headline,
        "id": article_id,
        "image": "https://news.example.test/image.png",
        "related": "AAPL",
        "source": "Example Wire",
        "summary": summary,
        "url": url,
    }


class FakeResponse:
    def __init__(self, payload) -> None:
        self._body = json.dumps(payload).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return None

    def read(self) -> bytes:
        return self._body


class FakeOpener:
    def __init__(self, responses=None, errors=None) -> None:
        self.responses = dict(responses or {})
        self.errors = dict(errors or {})
        self.requested: list = []

    def __call__(self, request, timeout=None):
        url = request.full_url.split("?")[0]
        self.requested.append(request.full_url)
        if url in self.errors:
            raise self.errors[url]
        if url in self.responses:
            return FakeResponse(self.responses[url])
        raise HTTPError(url, 404, "not found", {}, None)


class FakeTime:
    def __init__(self) -> None:
        self.now = 0.0
        self.sleeps = []

    def clock(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now += seconds


def make_connector(opener: FakeOpener) -> FinnhubNewsConnector:
    return FinnhubNewsConnector(
        client=FinnhubClient(
            api_key="test-key",
            opener=opener,
            requests_per_second=1000,
        )
    )


class FinnhubNewsConnectorTests(unittest.TestCase):
    def test_missing_api_key_is_reported_as_unavailable(self) -> None:
        with patch.dict(os.environ, {"FINNHUB_API_KEY": ""}, clear=False):
            self.assertIsNotNone(FinnhubNewsConnector.configuration_error())
            with self.assertRaises(ConnectorUnavailableError):
                FinnhubNewsConnector.from_environment()
            with self.assertRaises(ConnectorUnavailableError):
                FinnhubClient.from_environment()

    def test_from_environment_builds_when_key_is_present(self) -> None:
        with patch.dict(
            os.environ,
            {"FINNHUB_API_KEY": "test-key"},
            clear=False,
        ):
            connector = FinnhubNewsConnector.from_environment()
            self.assertIsNone(connector.configuration_error())

        self.assertEqual(connector.name, "news")
        self.assertEqual(connector.max_lookback_days, 30)

    def test_collect_maps_articles_into_unified_items(self) -> None:
        published = datetime(2026, 8, 1, 12, tzinfo=timezone.utc)
        opener = FakeOpener(
            responses={
                "https://finnhub.io/api/v1/company-news": [
                    article(published=published),
                    article(
                        article_id=101,
                        headline="Second headline",
                        url="https://news.example.test/second",
                        summary=None,
                    ),
                ]
            }
        )
        connector = make_connector(opener)

        items = connector.collect(
            CollectionRequest(
                tickers=("AAPL",),
                start_date=date(2026, 8, 1),
                end_date=date(2026, 8, 2),
                markets={"AAPL": "us"},
            )
        )

        self.assertEqual(len(items), 2)
        first = items[0]
        self.assertEqual(first.source, "news")
        self.assertEqual(first.source_type, "news")
        self.assertEqual(first.external_id, "100")
        self.assertEqual(first.tickers, ("AAPL",))
        self.assertEqual(first.market, "us")
        self.assertEqual(first.summary, "A short summary.")
        self.assertEqual(first.effective_at, published)
        self.assertEqual(first.published_at, published)
        self.assertEqual(first.raw_metadata["provider"], "finnhub")
        self.assertEqual(first.raw_metadata["symbol"], "AAPL")
        self.assertIsNone(items[1].summary)
        self.assertTrue(all(
            item.url.startswith("https://news.example.test/") for item in items
        ))

    def test_collect_deduplicates_same_article_id(self) -> None:
        opener = FakeOpener(
            responses={
                "https://finnhub.io/api/v1/company-news": [
                    article(),
                    article(),
                ]
            }
        )
        connector = make_connector(opener)

        items = connector.collect(
            CollectionRequest(
                tickers=("AAPL",),
                start_date=date(2026, 8, 1),
                end_date=date(2026, 8, 2),
            )
        )

        self.assertEqual(len(items), 1)

    def test_out_of_range_articles_are_filtered(self) -> None:
        opener = FakeOpener(
            responses={
                "https://finnhub.io/api/v1/company-news": [
                    article(published=datetime(2026, 7, 31, tzinfo=timezone.utc)),
                    article(
                        article_id=102,
                        published=datetime(2026, 8, 3, 23, tzinfo=timezone.utc),
                    ),
                ]
            }
        )
        connector = make_connector(opener)

        items = connector.collect(
            CollectionRequest(
                tickers=("AAPL",),
                start_date=date(2026, 8, 1),
                end_date=date(2026, 8, 2),
            )
        )

        self.assertEqual(items, [])

    def test_market_symbol_mapping(self) -> None:
        opener = FakeOpener(
            responses={
                "https://finnhub.io/api/v1/company-news": [article()]
            }
        )
        connector = make_connector(opener)
        request = CollectionRequest(
            tickers=("AAPL", "0700", "600519"),
            start_date=date(2026, 8, 1),
            end_date=date(2026, 8, 2),
            markets={"AAPL": "us", "0700": "hk", "600519": "cn"},
        )

        items = connector.collect(request)
        requested = opener.requested

        self.assertIn("symbol=AAPL", requested[0])
        self.assertIn("symbol=0700.HK", requested[1])
        self.assertIn("symbol=600519.SS", requested[2])
        self.assertIn("symbol=600519.SZ", requested[3])
        self.assertTrue(items)

    def test_cn_no_coverage_404_is_not_a_ticker_failure(self) -> None:
        opener = FakeOpener(errors={
            "https://finnhub.io/api/v1/company-news": HTTPError(
                "https://finnhub.io/api/v1/company-news",
                404,
                "not found",
                {},
                None,
            )
        })
        connector = make_connector(opener)

        items = connector.collect(
            CollectionRequest(
                tickers=("600519",),
                start_date=date(2026, 8, 1),
                end_date=date(2026, 8, 2),
                markets={"600519": "cn"},
            )
        )

        self.assertEqual(items, [])
        self.assertEqual(connector.last_errors, ())

    def test_us_http_failure_becomes_a_ticker_failure(self) -> None:
        opener = FakeOpener(errors={
            "https://finnhub.io/api/v1/company-news": HTTPError(
                "https://finnhub.io/api/v1/company-news",
                503,
                "unavailable",
                {},
                None,
            )
        })
        connector = make_connector(opener)

        with self.assertRaises(FinnhubNewsRequestError):
            connector.collect(
                CollectionRequest(
                    tickers=("AAPL",),
                    start_date=date(2026, 8, 1),
                    end_date=date(2026, 8, 2),
                )
            )

        self.assertEqual(len(connector.last_errors), 1)

    def test_retries_temporary_http_failure(self) -> None:
        calls = []

        def opener(request, timeout=None):
            url = request.full_url.split("?")[0]
            calls.append(url)
            if len(calls) == 1:
                raise HTTPError(url, 429, "rate limited", {}, None)
            return FakeResponse([article()])

        fake_time = FakeTime()
        connector = FinnhubNewsConnector(
            client=FinnhubClient(
                api_key="test-key",
                opener=opener,
                clock=fake_time.clock,
                sleeper=fake_time.sleep,
                max_retries=1,
                requests_per_second=1000,
            )
        )

        items = connector.collect(
            CollectionRequest(
                tickers=("AAPL",),
                start_date=date(2026, 8, 1),
                end_date=date(2026, 8, 2),
            )
        )

        self.assertEqual(len(calls), 2)
        self.assertEqual(len(items), 1)

    def test_failed_ticker_does_not_stop_the_next_ticker(self) -> None:
        def failing_opener(request, timeout=None):
            url = request.full_url
            if "symbol=FAIL" in url:
                raise HTTPError(url, 503, "unavailable", {}, None)
            return FakeResponse([article()])

        connector = FinnhubNewsConnector(
            client=FinnhubClient(
                api_key="test-key",
                opener=failing_opener,
                requests_per_second=1000,
            )
        )

        items = connector.collect(
            CollectionRequest(
                tickers=("GOOD", "FAIL"),
                start_date=date(2026, 8, 1),
                end_date=date(2026, 8, 2),
            )
        )

        self.assertEqual({item.tickers for item in items}, {("GOOD",)})
        self.assertEqual(len(connector.last_errors), 1)
        self.assertEqual(connector.last_errors[0][0], "FAIL")


class NewsPipelineIntegrationTests(unittest.TestCase):
    def test_pipeline_clamps_lookback_for_connectors_with_a_maximum(self) -> None:
        captured = []

        class ClampedConnector:
            name = "clamped"
            max_lookback_days = 7

            def collect(self, request: CollectionRequest):
                captured.append(request)
                return []

        pipeline = CollectionPipeline([ClampedConnector()])
        pipeline.collect(
            CollectionRequest(
                tickers=("AAPL",),
                start_date=date(2025, 1, 1),
                end_date=date(2026, 1, 1),
            )
        )

        self.assertEqual(captured[0].start_date, date(2025, 12, 25))

    def test_enabled_sec_and_news_are_both_collected(self) -> None:
        class FixtureNewsConnector:
            name = "news"

            def collect(self, request: CollectionRequest):
                return [
                    InformationItem(
                        source="news",
                        source_type="news",
                        external_id="news-1",
                        tickers=request.tickers,
                        issuer=request.tickers[0],
                        published_at=datetime(
                            2026, 8, 1, tzinfo=timezone.utc
                        ),
                        title="News headline",
                        document_type="news",
                        url="https://news.example.test/1",
                        collected_at=datetime(
                            2026, 8, 1, 12, tzinfo=timezone.utc
                        ),
                        market=request.market_for(request.tickers[0]),
                        summary="News summary",
                    )
                ]

        class FixtureSECConnector:
            name = "sec"

            def collect(self, request: CollectionRequest):
                return [
                    InformationItem(
                        source="sec",
                        source_type="regulatory_filing",
                        external_id="sec-1",
                        tickers=request.tickers,
                        issuer="Example Issuer",
                        published_at=datetime(
                            2026, 8, 1, tzinfo=timezone.utc
                        ),
                        title="SEC filing",
                        document_type="8-K",
                        url="https://www.sec.gov/example",
                        collected_at=datetime(
                            2026, 8, 1, 12, tzinfo=timezone.utc
                        ),
                        market="us",
                    )
                ]

        with TemporaryDirectory() as temporary_directory:
            directory = Path(temporary_directory)
            settings_path = directory / "settings.yaml"
            settings_path.write_text(
                "enabled_sources:\n"
                "  - sec\n"
                "  - news\n"
                "database_path: data/items.sqlite3\n",
                encoding="utf-8",
            )
            registry = SourceRegistry()
            registry.register("sec", FixtureSECConnector)
            registry.register("news", FixtureNewsConnector)

            result = run_ticker_collection(
                tickers=("AAPL",),
                settings_path=settings_path,
                start_date=date(2026, 8, 1),
                end_date=date(2026, 8, 2),
                registry=registry,
            )

            self.assertEqual(
                {item.source for item in result.items},
                {"sec", "news"},
            )
            self.assertEqual(result.stored_count, 2)

    def test_news_items_enter_mixed_feed_and_mark_news_connected(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            database_path = Path(temporary_directory) / "web.sqlite3"
            items = SQLiteInformationRepository(database_path)
            repository = WebRepository(
                database_path,
                allowed_sources=("sec", "news"),
                known_sources=[],
                implemented_sources=("sec", "news"),
            )

            class Resolver:
                def resolve(self, ticker: str):
                    return {
                        "AAPL": {
                            "ticker": "AAPL",
                            "name": "Apple Inc.",
                            "exchange": "Nasdaq",
                            "cik": "0000320193",
                            "mapping_status": "mapped",
                        }
                    }.get(ticker)

            repository.add_companies_batch("AAPL", ("holdings",), Resolver())
            items.save(
                [
                    InformationItem(
                        source="news",
                        source_type="news",
                        external_id="news-1",
                        tickers=("AAPL",),
                        issuer="AAPL",
                        published_at=datetime(
                            2026, 8, 1, tzinfo=timezone.utc
                        ),
                        title="News headline",
                        document_type="news",
                        url="https://news.example.test/1",
                        collected_at=datetime(
                            2026, 8, 1, 12, tzinfo=timezone.utc
                        ),
                        market="us",
                        summary="News summary",
                        effective_at=datetime(
                            2026, 8, 1, 12, tzinfo=timezone.utc
                        ),
                    )
                ]
            )

            news_feed = repository.query_feed(
                FeedFilters(information_type="news")
            )
            statuses = {
                record["type"]: record
                for record in repository.source_statuses(
                    now=datetime(2026, 8, 1, 13, tzinfo=timezone.utc)
                )
            }

            self.assertEqual(news_feed.total, 1)
            self.assertEqual(news_feed.items[0]["source"], "news")
            self.assertEqual(news_feed.items[0]["summary"], "News summary")
            self.assertEqual(statuses["News"]["status"], "connected")
            self.assertEqual(statuses["News"]["provider"], "Finnhub News")


if __name__ == "__main__":
    unittest.main()
