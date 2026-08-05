from datetime import date, timezone
import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any, Dict
import unittest
from unittest.mock import patch

from investment_monitor import (
    CollectionRequest,
    ConnectorUnavailableError,
    SECConnector,
    SECError,
    SECRequestError,
)
from investment_monitor.sources.sec.connector import (
    COMPANY_TICKERS_URL,
    SUBMISSIONS_BASE_URL,
    TickerCIKResolver,
)

FIXTURE_DIRECTORY = Path(__file__).parent / "fixtures" / "sec"


def load_fixture(name: str) -> Any:
    with (FIXTURE_DIRECTORY / name).open("r", encoding="utf-8") as fixture_file:
        return json.load(fixture_file)


class FixtureSECClient:
    def __init__(self) -> None:
        self.responses: Dict[str, Any] = {
            COMPANY_TICKERS_URL: load_fixture("company_tickers.json"),
            (
                f"{SUBMISSIONS_BASE_URL}/CIK0000320193.json"
            ): load_fixture("CIK0000320193.json"),
            (
                f"{SUBMISSIONS_BASE_URL}/"
                "CIK0000320193-submissions-001.json"
            ): load_fixture("CIK0000320193-submissions-001.json"),
        }
        self.requested_urls = []

    def get_json(self, url: str) -> Any:
        self.requested_urls.append(url)
        if url.endswith("CIK0000999999.json"):
            raise SECRequestError("Fixture submission request failed.")
        return self.responses[url]


class SECConnectorTests(unittest.TestCase):
    def make_connector(
        self, client: FixtureSECClient, cache_path: Path
    ) -> SECConnector:
        resolver = TickerCIKResolver(client=client, cache_path=cache_path)
        return SECConnector(client=client, resolver=resolver)

    def test_maps_and_filters_recent_filings(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            client = FixtureSECClient()
            connector = self.make_connector(
                client, Path(temporary_directory) / "tickers.json"
            )
            request = CollectionRequest(
                tickers=("aapl",),
                start_date=date(2026, 1, 1),
                end_date=date(2026, 1, 31),
            )

            items = connector.collect(request)

        self.assertEqual(len(items), 2)
        annual_report, current_report = items
        self.assertEqual(annual_report.source, "sec")
        self.assertEqual(annual_report.source_type, "regulatory_filing")
        self.assertEqual(
            annual_report.external_id, "0000320193-26-000010"
        )
        self.assertEqual(annual_report.tickers, ("AAPL",))
        self.assertEqual(annual_report.issuer, "Apple Inc.")
        self.assertEqual(annual_report.title, "Annual Report")
        self.assertEqual(annual_report.document_type, "10-K")
        self.assertEqual(
            annual_report.url,
            "https://www.sec.gov/Archives/edgar/data/320193/"
            "000032019326000010/aapl-20251227.htm",
        )
        self.assertEqual(annual_report.published_at.tzinfo, timezone.utc)
        self.assertEqual(current_report.title, "Form 8-K Current Report")
        self.assertEqual(connector.last_errors, ())

    def test_loads_an_overlapping_historical_submission_file(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            client = FixtureSECClient()
            connector = self.make_connector(
                client, Path(temporary_directory) / "tickers.json"
            )
            request = CollectionRequest(
                tickers=("AAPL",),
                start_date=date(2022, 7, 1),
                end_date=date(2022, 7, 31),
            )

            items = connector.collect(request)

        self.assertEqual(len(items), 1)
        self.assertEqual(items[0].external_id, "0000320193-22-000100")
        self.assertIn(
            f"{SUBMISSIONS_BASE_URL}/CIK0000320193-submissions-001.json",
            client.requested_urls,
        )

    def test_failed_ticker_does_not_stop_the_next_ticker(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            client = FixtureSECClient()
            connector = self.make_connector(
                client, Path(temporary_directory) / "tickers.json"
            )
            request = CollectionRequest(
                tickers=("FAIL", "AAPL"),
                start_date=date(2026, 1, 1),
                end_date=date(2026, 1, 31),
            )

            with self.assertLogs(
                "investment_monitor.sources.sec.connector", level="WARNING"
            ):
                items = connector.collect(request)

        self.assertEqual(len(items), 2)
        self.assertEqual({item.tickers for item in items}, {("AAPL",)})
        self.assertEqual(len(connector.last_errors), 1)
        self.assertEqual(connector.last_errors[0].ticker, "FAIL")

    def test_non_us_market_ticker_is_skipped_without_calling_sec(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            client = FixtureSECClient()
            connector = self.make_connector(
                client, Path(temporary_directory) / "tickers.json"
            )
            request = CollectionRequest(
                tickers=("AAPL",),
                start_date=date(2026, 1, 1),
                end_date=date(2026, 1, 31),
                markets={"AAPL": "hk"},
            )

            with self.assertRaisesRegex(SECError, "does not cover market 'hk'"):
                connector.collect(request)

        self.assertEqual(client.requested_urls, [])

    def test_missing_user_agent_is_reported_as_unavailable(self) -> None:
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("SEC_USER_AGENT", None)

            self.assertIsNotNone(SECConnector.configuration_error())
            with self.assertRaises(ConnectorUnavailableError):
                SECConnector.from_environment()

    def test_registry_skips_sec_when_user_agent_is_missing(self) -> None:
        from investment_monitor import SourceRegistry, create_default_registry

        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("SEC_USER_AGENT", None)
            os.environ.pop("FINNHUB_API_KEY", None)
            registry = create_default_registry()

            unavailable: list = []
            connectors = registry.load_enabled(
                ["sec"],
                unavailable=unavailable,
            )

            self.assertEqual(connectors, [])
            self.assertEqual(unavailable, ["sec"])
            self.assertIsInstance(registry, SourceRegistry)

    def test_ticker_mapping_is_reused_from_the_local_cache(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            cache_path = Path(temporary_directory) / "tickers.json"
            downloading_client = FixtureSECClient()
            first_resolver = TickerCIKResolver(
                client=downloading_client, cache_path=cache_path
            )

            first_result = first_resolver.resolve("AAPL")

            cached_client = FixtureSECClient()
            cached_client.responses.pop(COMPANY_TICKERS_URL)
            second_resolver = TickerCIKResolver(
                client=cached_client, cache_path=cache_path
            )
            second_result = second_resolver.resolve("AAPL")

        self.assertEqual(first_result, (320193, "Apple Inc."))
        self.assertEqual(second_result, first_result)
        self.assertNotIn(COMPANY_TICKERS_URL, cached_client.requested_urls)

    def test_stale_ticker_cache_is_used_when_refresh_temporarily_fails(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            cache_path = Path(temporary_directory) / "tickers.json"
            cache_path.write_text(
                json.dumps(load_fixture("company_tickers.json")),
                encoding="utf-8",
            )
            client = FixtureSECClient()

            def failed_get_json(url: str) -> Any:
                client.requested_urls.append(url)
                raise SECRequestError("Temporary SEC mapping failure")

            client.get_json = failed_get_json  # type: ignore[method-assign]
            resolver = TickerCIKResolver(
                client=client,
                cache_path=cache_path,
                cache_ttl_seconds=1,
                clock=lambda: cache_path.stat().st_mtime + 60,
            )

            with self.assertLogs(
                "investment_monitor.sources.sec.connector", level="WARNING"
            ):
                result = resolver.resolve("AAPL")

        self.assertEqual(result, (320193, "Apple Inc."))
        self.assertEqual(client.requested_urls, [COMPANY_TICKERS_URL])


if __name__ == "__main__":
    unittest.main()
