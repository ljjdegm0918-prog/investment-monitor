from datetime import date, datetime, timezone
import io
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from urllib.error import HTTPError
from urllib.parse import parse_qs, urlsplit
from zoneinfo import ZoneInfo

from investment_monitor import CollectionPipeline, SQLiteInformationRepository
from investment_monitor.content_relevance import ContentRelevanceFilter
from investment_monitor.models import ALLOWED_MARKETS, CollectionRequest
from investment_monitor.config import load_settings
from investment_monitor.registry import SOURCE_MARKETS, create_default_registry
from investment_monitor.web_repository import CONNECTOR_REGIONS, SOURCE_LABELS
from investment_monitor.sources.regional_press import (
    PUBLISHER_DISCOVERY_PROFILES,
    REGIONAL_PRESS_PROFILES,
    PublisherDiscoveryClient,
    PublisherDiscoveryDataError,
    RegionalPressClient,
    RegionalPressConnector,
    RegionalPressDataError,
    RegionalPressRequestError,
    RegionalPublisherDiscoveryConnector,
)
from investment_monitor.sources.regional_press.client import parse_regional_rss
from investment_monitor.sources.regional_press.discovery import (
    parse_publisher_discovery_rss,
)


RSS_FIXTURE = b"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0"
     xmlns:atom="http://www.w3.org/2005/Atom"
     xmlns:dc="http://purl.org/dc/elements/1.1/">
  <channel>
    <title>Example Business</title>
    <item>
      <guid>story-samsung</guid>
      <title>Samsung Electronics raises its investment plan</title>
      <atom:link href="https://www.hankyung.com/business/samsung-plan" />
      <link>https://www.hankyung.com/business/samsung-plan</link>
      <pubDate>Tue, 25 Aug 2026 09:30:00 +0900</pubDate>
      <description><![CDATA[<p>Samsung Electronics said the plan starts today.</p>]]></description>
    </item>
    <item>
      <guid>story-other</guid>
      <title>Central bank holds interest rates</title>
      <link>https://www.hankyung.com/business/rates</link>
      <pubDate>Tue, 25 Aug 2026 10:00:00 +0900</pubDate>
      <description>Policy makers left rates unchanged.</description>
    </item>
    <item>
      <guid>story-old</guid>
      <title>Samsung Electronics older item</title>
      <link>https://www.hankyung.com/business/old</link>
      <pubDate>Sat, 01 Aug 2026 09:30:00 +0900</pubDate>
    </item>
  </channel>
</rss>
"""

DISCOVERY_RSS_FIXTURE = b"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0"><channel><title>Google News</title>
  <item>
    <guid>caixin-approved</guid>
    <title>Guizhou Moutai reports revenue growth - Caixin Global</title>
    <link>https://news.google.com/rss/articles/approved</link>
    <pubDate>Tue, 25 Aug 2026 09:30:00 GMT</pubDate>
    <description>Snippet deliberately not retained.</description>
    <source url="https://companies.caixin.com">Caixin Global</source>
  </item>
  <item>
    <guid>wrong-publisher</guid>
    <title>Guizhou Moutai mentioned by an unrelated publisher</title>
    <link>https://news.google.com/rss/articles/wrong-publisher</link>
    <pubDate>Tue, 25 Aug 2026 10:30:00 GMT</pubDate>
    <source url="https://evil.example">Unknown</source>
  </item>
</channel></rss>
"""


class FakeResponse:
    def __init__(self, body, *, content_length=None, response_url=None):
        self._body = io.BytesIO(body)
        self._response_url = response_url
        self.headers = {}
        if content_length is not None:
            self.headers["Content-Length"] = str(content_length)

    def read(self, size=-1):
        return self._body.read(size)

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return None

    def geturl(self):
        return self._response_url


class FakeClient:
    def __init__(self, records):
        self.records = records
        self.calls = []

    def fetch_news(self, profile, start_date, end_date):
        self.calls.append((profile.source, start_date, end_date))
        return list(self.records)


class FailingClient:
    def __init__(self, error):
        self.error = error
        self.calls = []

    def fetch_news(self, profile, start_date, end_date):
        self.calls.append((profile.source, start_date, end_date))
        raise self.error


class FakeDiscoveryClient:
    def __init__(self, records):
        self.records = records
        self.calls = []

    def fetch_news(self, profile, company_query, start_date, end_date):
        self.calls.append((
            profile.source,
            company_query,
            start_date,
            end_date,
        ))
        return list(self.records)


class IncludingRelevanceClient:
    model = "regional-relevance-fixture"

    def generate(self, *, system_prompt, user_prompt, language):
        return {"results": [{
            "id": "0",
            "decision": "include",
            "role": "primary_subject",
            "reason": "Apple is the story's subject.",
        }]}


class RegionalPressParserTests(unittest.TestCase):
    def test_parser_keeps_feed_metadata_and_applies_local_calendar_range(self):
        records = parse_regional_rss(
            RSS_FIXTURE,
            feed_url="https://publisher.example/rss",
            start_date=date(2026, 8, 25),
            end_date=date(2026, 8, 25),
            zone=ZoneInfo("Asia/Seoul"),
        )

        self.assertEqual(len(records), 2)
        self.assertEqual(records[0]["external_id"], "story-samsung")
        self.assertEqual(
            records[0]["summary"],
            "Samsung Electronics said the plan starts today.",
        )
        self.assertEqual(
            records[0]["published"],
            datetime(2026, 8, 25, 0, 30, tzinfo=timezone.utc),
        )

    def test_parser_rejects_non_rss_and_ignores_invalid_items(self):
        with self.assertRaises(RegionalPressDataError):
            parse_regional_rss(
                b"<feed></feed>",
                feed_url="https://publisher.example/rss",
                start_date=date(2026, 8, 25),
                end_date=date(2026, 8, 25),
                zone=ZoneInfo("UTC"),
            )

    def test_parser_treats_naive_dates_as_publisher_local_time(self):
        template = b"""<rss><channel><item>
          <guid>story-local</guid><title>Issuer reports results</title>
          <link>https://publisher.example/story</link>
          <pubDate>2026-08-25 23:30:00</pubDate>
        </item></channel></rss>"""
        cases = (
            ("Asia/Seoul", datetime(2026, 8, 25, 14, 30, tzinfo=timezone.utc)),
            (
                "America/Toronto",
                datetime(2026, 8, 26, 3, 30, tzinfo=timezone.utc),
            ),
        )
        for timezone_name, expected in cases:
            with self.subTest(timezone=timezone_name):
                records = parse_regional_rss(
                    template,
                    feed_url="https://publisher.example/rss",
                    start_date=date(2026, 8, 25),
                    end_date=date(2026, 8, 25),
                    zone=ZoneInfo(timezone_name),
                )
                self.assertEqual(records[0]["published"], expected)

    def test_parser_rejects_non_https_item_links(self):
        body = RSS_FIXTURE.replace(
            b"https://www.hankyung.com/business/samsung-plan",
            b"http://www.hankyung.com/business/samsung-plan",
        )
        with self.assertRaises(RegionalPressDataError):
            parse_regional_rss(
                body,
                feed_url="https://www.hankyung.com/feed/finance",
                start_date=date(2026, 8, 25),
                end_date=date(2026, 8, 25),
                zone=ZoneInfo("Asia/Seoul"),
            )


class RegionalPressClientTests(unittest.TestCase):
    def test_client_caches_feed_per_profile_and_range(self):
        calls = []

        def opener(request, timeout):
            calls.append((request.full_url, timeout))
            return FakeResponse(RSS_FIXTURE)

        selected = next(p for p in REGIONAL_PRESS_PROFILES if p.market == "kr")
        client = RegionalPressClient(opener=opener, sleeper=lambda _seconds: None)
        first = client.fetch_news(
            selected, date(2026, 8, 25), date(2026, 8, 25)
        )
        second = client.fetch_news(
            selected, date(2026, 8, 25), date(2026, 8, 25)
        )

        self.assertEqual(first, second)
        self.assertEqual(len(calls), 1)

    def test_client_bounds_response_size_and_maps_http_failures(self):
        selected = next(p for p in REGIONAL_PRESS_PROFILES if p.market == "kr")
        oversized = RegionalPressClient(
            opener=lambda *_args, **_kwargs: FakeResponse(
                b"x", content_length=5000
            ),
            max_response_bytes=1024,
        )
        with self.assertRaises(RegionalPressDataError):
            oversized.fetch_news(
                selected, date(2026, 8, 25), date(2026, 8, 25)
            )

        def failing(request, timeout):
            raise HTTPError(request.full_url, 403, "Forbidden", {}, None)

        blocked = RegionalPressClient(opener=failing, max_retries=0)
        with self.assertRaises(RegionalPressRequestError):
            blocked.fetch_news(
                selected, date(2026, 8, 25), date(2026, 8, 25)
            )

    def test_client_rejects_external_article_and_redirect_hosts(self):
        selected = next(p for p in REGIONAL_PRESS_PROFILES if p.market == "kr")
        external_item = RSS_FIXTURE.replace(
            b"www.hankyung.com", b"evil.example"
        )
        client = RegionalPressClient(
            opener=lambda *_args, **_kwargs: FakeResponse(external_item),
        )
        with self.assertRaises(RegionalPressDataError):
            client.fetch_news(
                selected, date(2026, 8, 25), date(2026, 8, 25)
            )

        redirected = RegionalPressClient(
            opener=lambda *_args, **_kwargs: FakeResponse(
                RSS_FIXTURE,
                response_url="https://evil.example/feed",
            ),
        )
        with self.assertRaises(RegionalPressDataError):
            redirected.fetch_news(
                selected, date(2026, 8, 25), date(2026, 8, 25)
            )


class PublisherDiscoveryTests(unittest.TestCase):
    def test_parser_keeps_only_verified_publisher_source_and_no_summary(self):
        records = parse_publisher_discovery_rss(
            DISCOVERY_RSS_FIXTURE,
            start_date=date(2026, 8, 25),
            end_date=date(2026, 8, 25),
            zone=ZoneInfo("Asia/Shanghai"),
            publisher_domains=("caixin.com",),
        )

        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["external_id"], "caixin-approved")
        self.assertEqual(records[0]["publisher_name"], "Caixin Global")
        self.assertEqual(
            records[0]["publisher_url"],
            "https://companies.caixin.com",
        )
        self.assertIsNone(records[0]["summary"])

    def test_client_builds_site_scoped_query_caches_and_rejects_redirect(self):
        selected = next(
            p for p in PUBLISHER_DISCOVERY_PROFILES if p.market == "cn"
        )
        calls = []

        def opener(request, timeout):
            calls.append((request.full_url, timeout))
            return FakeResponse(DISCOVERY_RSS_FIXTURE)

        client = PublisherDiscoveryClient(
            opener=opener,
            sleeper=lambda _seconds: None,
        )
        first = client.fetch_news(
            selected,
            "Guizhou Moutai",
            date(2026, 8, 25),
            date(2026, 8, 25),
        )
        second = client.fetch_news(
            selected,
            "Guizhou Moutai",
            date(2026, 8, 25),
            date(2026, 8, 25),
        )

        self.assertEqual(first, second)
        self.assertEqual(len(calls), 1)
        query = parse_qs(urlsplit(calls[0][0]).query)["q"][0]
        self.assertEqual(query, '"Guizhou Moutai" site:caixin.com')

        redirected = PublisherDiscoveryClient(
            opener=lambda *_args, **_kwargs: FakeResponse(
                DISCOVERY_RSS_FIXTURE,
                response_url="https://evil.example/rss",
            ),
        )
        with self.assertRaises(PublisherDiscoveryDataError):
            redirected.fetch_news(
                selected,
                "Guizhou Moutai",
                date(2026, 8, 25),
                date(2026, 8, 25),
            )

    def test_connector_maps_verified_discovery_without_publisher_body(self):
        selected = next(
            p for p in PUBLISHER_DISCOVERY_PROFILES if p.market == "cn"
        )
        records = parse_publisher_discovery_rss(
            DISCOVERY_RSS_FIXTURE,
            start_date=date(2026, 8, 25),
            end_date=date(2026, 8, 25),
            zone=ZoneInfo("Asia/Shanghai"),
            publisher_domains=selected.publisher_domains,
        )
        client = FakeDiscoveryClient(records)
        connector = RegionalPublisherDiscoveryConnector(
            selected,
            client=client,
            universe={
                "600519": {"name": "Guizhou Moutai Co., Ltd."},
            },
        )

        items = connector.collect(CollectionRequest(
            tickers=("600519",),
            start_date=date(2026, 8, 25),
            end_date=date(2026, 8, 25),
            markets={"600519": "cn"},
        ))

        self.assertEqual(len(items), 1)
        self.assertEqual(items[0].external_id, "600519:caixin-approved")
        self.assertEqual(items[0].document_type, "publisher_news_discovery")
        self.assertIsNone(items[0].summary)
        self.assertEqual(
            items[0].raw_metadata["discovery_method"],
            "publisher_domain_scoped",
        )
        self.assertFalse(items[0].raw_metadata["publisher_link_resolved"])
        self.assertFalse(items[0].raw_metadata["article_body_fetched"])
        self.assertEqual(client.calls[0][1], "guizhou moutai")

    def test_discovery_profiles_fill_every_non_venue_region(self):
        direct_markets = {profile.market for profile in REGIONAL_PRESS_PROFILES}
        discovery_markets = {
            profile.market for profile in PUBLISHER_DISCOVERY_PROFILES
        }
        national_markets = set(ALLOWED_MARKETS) - {
            "unknown", "aq", "cxe", "trq", "eux", "emf",
        }

        self.assertEqual(len(PUBLISHER_DISCOVERY_PROFILES), 9)
        self.assertEqual(direct_markets | discovery_markets, national_markets)
        self.assertFalse(direct_markets & discovery_markets)

    def test_discovery_pipeline_requires_ai_gate_before_persistence(self):
        selected = next(
            p for p in PUBLISHER_DISCOVERY_PROFILES if p.market == "cn"
        )
        records = parse_publisher_discovery_rss(
            DISCOVERY_RSS_FIXTURE,
            start_date=date(2026, 8, 25),
            end_date=date(2026, 8, 25),
            zone=ZoneInfo("Asia/Shanghai"),
            publisher_domains=selected.publisher_domains,
        )
        connector = RegionalPublisherDiscoveryConnector(
            selected,
            client=FakeDiscoveryClient(records),
            universe={
                "600519": {"name": "Guizhou Moutai Co., Ltd."},
            },
        )
        request = CollectionRequest(
            tickers=("600519",),
            start_date=date(2026, 8, 25),
            end_date=date(2026, 8, 25),
            markets={"600519": "cn"},
        )

        with TemporaryDirectory() as temporary_directory:
            repository = SQLiteInformationRepository(
                Path(temporary_directory) / "discovery.sqlite3"
            )
            pipeline = CollectionPipeline(
                [connector],
                repository=repository,
                source_markets={selected.source: "cn"},
            )
            items = pipeline.collect(request)
            stored_count = repository.count()

        self.assertEqual(items, [])
        self.assertEqual(stored_count, 0)
        self.assertEqual(len(pipeline.last_failures), 1)
        self.assertIn(
            "CONTENT_RELEVANCE_AI_ENABLED=true",
            pipeline.last_failures[0].message,
        )

    def test_discovery_pipeline_persists_after_ai_primary_subject_decision(self):
        selected = next(
            p for p in PUBLISHER_DISCOVERY_PROFILES if p.market == "cn"
        )
        records = parse_publisher_discovery_rss(
            DISCOVERY_RSS_FIXTURE,
            start_date=date(2026, 8, 25),
            end_date=date(2026, 8, 25),
            zone=ZoneInfo("Asia/Shanghai"),
            publisher_domains=selected.publisher_domains,
        )
        connector = RegionalPublisherDiscoveryConnector(
            selected,
            client=FakeDiscoveryClient(records),
            universe={
                "600519": {"name": "Guizhou Moutai Co., Ltd."},
            },
        )
        request = CollectionRequest(
            tickers=("600519",),
            start_date=date(2026, 8, 25),
            end_date=date(2026, 8, 25),
            markets={"600519": "cn"},
        )

        with TemporaryDirectory() as temporary_directory:
            repository = SQLiteInformationRepository(
                Path(temporary_directory) / "discovery.sqlite3"
            )
            pipeline = CollectionPipeline(
                [connector],
                repository=repository,
                source_markets={selected.source: "cn"},
                item_filter=ContentRelevanceFilter(
                    client=IncludingRelevanceClient()
                ),
            )
            items = pipeline.collect(request)
            stored = repository.query(
                ticker="600519",
                source=selected.source,
            )

        self.assertEqual(len(items), 1)
        self.assertEqual(len(stored), 1)
        self.assertEqual(
            stored[0].raw_metadata["content_relevance"]["role"],
            "primary_subject",
        )


class RegionalPressConnectorTests(unittest.TestCase):
    def test_connector_matches_company_name_and_maps_provenance(self):
        selected = next(p for p in REGIONAL_PRESS_PROFILES if p.market == "kr")
        records = parse_regional_rss(
            RSS_FIXTURE,
            feed_url=selected.feed_urls[0],
            start_date=date(2026, 8, 25),
            end_date=date(2026, 8, 25),
            zone=ZoneInfo("Asia/Seoul"),
        )
        client = FakeClient(records)
        connector = RegionalPressConnector(
            selected,
            client=client,
            universe={"005930": {"name": "Samsung Electronics Co., Ltd."}},
        )

        items = connector.collect(CollectionRequest(
            tickers=("005930",),
            start_date=date(2026, 8, 25),
            end_date=date(2026, 8, 25),
            markets={"005930": "kr"},
        ))

        self.assertEqual(len(items), 1)
        item = items[0]
        self.assertEqual(item.source, selected.source)
        self.assertEqual(item.source_type, "news")
        self.assertEqual(item.tickers, ("005930",))
        self.assertEqual(item.issuer, "Samsung Electronics Co., Ltd.")
        self.assertEqual(item.external_id, "005930:story-samsung")
        self.assertEqual(
            item.raw_metadata["source_role"],
            "regional_authoritative_press",
        )
        self.assertFalse(item.raw_metadata["article_body_fetched"])
        self.assertIn("samsung electronics", item.raw_metadata["matched_aliases"])

    def test_connector_skips_wrong_market_and_unrelated_articles(self):
        selected = next(p for p in REGIONAL_PRESS_PROFILES if p.market == "kr")
        client = FakeClient([{
            "title": "Central bank holds rates",
            "summary": "No company was discussed.",
            "url": "https://publisher.example/rates",
            "published": datetime(2026, 8, 25, tzinfo=timezone.utc),
            "feed_url": selected.feed_urls[0],
        }])
        connector = RegionalPressConnector(
            selected,
            client=client,
            universe={"005930": {"name": "Samsung Electronics"}},
        )
        wrong_market = connector.collect(CollectionRequest(
            tickers=("005930",),
            start_date=date(2026, 8, 25),
            end_date=date(2026, 8, 25),
            markets={"005930": "jp"},
        ))
        unrelated = connector.collect(CollectionRequest(
            tickers=("005930",),
            start_date=date(2026, 8, 25),
            end_date=date(2026, 8, 25),
            markets={"005930": "kr"},
        ))

        self.assertEqual(wrong_market, [])
        self.assertEqual(unrelated, [])
        self.assertEqual(len(client.calls), 1)

    def test_connector_requires_identity_and_never_uses_bare_ticker_aliases(self):
        selected = next(p for p in REGIONAL_PRESS_PROFILES if p.market == "us")
        records = [{
            "external_id": "generic-words",
            "title": "All cat owners compare BRK plans with ABC",
            "summary": "Ordinary words, not a company story.",
            "url": "https://www.marketwatch.com/story/generic-words",
            "published": datetime(2026, 8, 25, tzinfo=timezone.utc),
            "feed_url": selected.feed_urls[0],
        }]
        client = FakeClient(records)
        connector = RegionalPressConnector(
            selected,
            client=client,
            universe={
                "ALL": {"name": "The Allstate Corporation"},
                "CAT": {"name": "Caterpillar Inc."},
                "BRK.B": {"name": "Berkshire Hathaway Inc."},
                "ABC": {"name": "ABC Holdings"},
            },
        )

        items = connector.collect(CollectionRequest(
            tickers=("ALL", "CAT", "BRK.B", "ABC", "MISSING"),
            start_date=date(2026, 8, 25),
            end_date=date(2026, 8, 25),
            markets={ticker: "us" for ticker in (
                "ALL", "CAT", "BRK.B", "ABC", "MISSING"
            )},
        ))

        self.assertEqual(items, [])
        self.assertEqual(len(client.calls), 1)
        self.assertEqual(
            connector.last_errors,
            (("MISSING", "no_universe_identity: MISSING"),),
        )
        self.assertEqual(connector.last_collection_status, "partial")

    def test_connector_fetches_once_and_keeps_guid_when_url_changes(self):
        selected = next(p for p in REGIONAL_PRESS_PROFILES if p.market == "us")
        first_url = "https://www.marketwatch.com/story/apple-results?mod=rss"
        client = FakeClient([{
            "external_id": "stable-guid",
            "title": "Apple reports quarterly results",
            "summary": "Apple Inc. reported its results.",
            "url": first_url,
            "published": datetime(2026, 8, 25, tzinfo=timezone.utc),
            "feed_url": selected.feed_urls[0],
        }])
        connector = RegionalPressConnector(
            selected,
            client=client,
            universe={
                "AAPL": {"name": "Apple Inc."},
                "MSFT": {"name": "Microsoft Corporation"},
            },
        )
        request = CollectionRequest(
            tickers=("AAPL", "MSFT"),
            start_date=date(2026, 8, 25),
            end_date=date(2026, 8, 25),
            markets={"AAPL": "us", "MSFT": "us"},
        )

        first = connector.collect(request)
        client.records[0]["url"] = (
            "https://www.marketwatch.com/story/apple-results?mod=updated"
        )
        second = connector.collect(request)

        self.assertEqual(len(client.calls), 2)
        self.assertEqual(first[0].external_id, "AAPL:stable-guid")
        self.assertEqual(second[0].external_id, "AAPL:stable-guid")

    def test_connector_failing_feed_is_requested_once_for_many_tickers(self):
        selected = next(p for p in REGIONAL_PRESS_PROFILES if p.market == "us")
        client = FailingClient(RegionalPressRequestError("feed unavailable"))
        connector = RegionalPressConnector(
            selected,
            client=client,
            universe={
                "AAPL": {"name": "Apple Inc."},
                "MSFT": {"name": "Microsoft Corporation"},
            },
        )
        with self.assertRaises(RegionalPressRequestError):
            connector.collect(CollectionRequest(
                tickers=("AAPL", "MSFT"),
                start_date=date(2026, 8, 25),
                end_date=date(2026, 8, 25),
                markets={"AAPL": "us", "MSFT": "us"},
            ))

        self.assertEqual(len(client.calls), 1)
        self.assertEqual(connector.last_collection_status, "failure")

    def test_source_wide_pipeline_applies_ai_gate_before_sqlite(self):
        selected = next(p for p in REGIONAL_PRESS_PROFILES if p.market == "us")
        client = FakeClient([{
            "external_id": "apple-subject",
            "title": "Apple launches a new product",
            "summary": "Apple Inc. announced the product today.",
            "url": "https://www.marketwatch.com/story/apple-product",
            "published": datetime(2026, 8, 25, tzinfo=timezone.utc),
            "feed_url": selected.feed_urls[0],
        }])
        connector = RegionalPressConnector(
            selected,
            client=client,
            universe={"AAPL": {"name": "Apple Inc."}},
        )
        request = CollectionRequest(
            tickers=("AAPL",),
            start_date=date(2026, 8, 25),
            end_date=date(2026, 8, 25),
            markets={"AAPL": "us"},
        )

        with TemporaryDirectory() as temporary_directory:
            repository = SQLiteInformationRepository(
                Path(temporary_directory) / "regional.sqlite3"
            )
            pipeline = CollectionPipeline(
                [connector],
                repository=repository,
                source_markets={selected.source: "us"},
                item_filter=ContentRelevanceFilter(
                    client=IncludingRelevanceClient()
                ),
            )
            items = pipeline.collect(request)
            stored = repository.query(ticker="AAPL", source=selected.source)

        self.assertEqual(len(client.calls), 1)
        self.assertEqual(len(items), 1)
        self.assertEqual(len(stored), 1)
        self.assertEqual(
            stored[0].raw_metadata["content_relevance"]["role"],
            "primary_subject",
        )
        self.assertEqual(pipeline.last_events[0].ticker, "*")

    def test_profiles_are_unique_https_and_not_venue_markets(self):
        sources = [profile.source for profile in REGIONAL_PRESS_PROFILES]
        self.assertEqual(len(sources), len(set(sources)))
        self.assertTrue(all(
            url.startswith("https://")
            for selected in REGIONAL_PRESS_PROFILES
            for url in selected.feed_urls
        ))
        self.assertFalse(
            {"aq", "cxe", "trq", "eux", "emf"}
            & {profile.market for profile in REGIONAL_PRESS_PROFILES}
        )

    def test_profiles_are_registered_and_market_scoped(self):
        registry = create_default_registry()
        enabled = set(load_settings(Path("config/settings.yaml")).enabled_sources)
        for selected in REGIONAL_PRESS_PROFILES:
            with self.subTest(source=selected.source):
                self.assertIsNotNone(registry.factory_for(selected.source))
                self.assertEqual(SOURCE_MARKETS[selected.source], selected.market)
                self.assertIn(selected.source, enabled)
                self.assertIn(selected.source, CONNECTOR_REGIONS)
                self.assertEqual(SOURCE_LABELS[selected.source], selected.label)
        for selected in PUBLISHER_DISCOVERY_PROFILES:
            with self.subTest(source=selected.source):
                self.assertIsNotNone(registry.factory_for(selected.source))
                self.assertEqual(SOURCE_MARKETS[selected.source], selected.market)
                self.assertIn(selected.source, enabled)
                self.assertIn(selected.source, CONNECTOR_REGIONS)
                self.assertEqual(SOURCE_LABELS[selected.source], selected.label)


if __name__ == "__main__":
    unittest.main()
