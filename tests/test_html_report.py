from datetime import date, datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import List
import unittest

from investment_monitor import (
    CollectionFailure,
    CollectionRequest,
    InformationItem,
    MockCommunityConnector,
    SQLiteInformationRepository,
    SourceRegistry,
    UniverseEntry,
    generate_html_report,
    run_workflow,
)


def make_item(
    *,
    source: str,
    source_type: str,
    external_id: str,
    ticker: str,
    published_at: datetime,
    title: str,
    document_type: str,
    url: str,
    generated: bool = False,
) -> InformationItem:
    return InformationItem(
        source=source,
        source_type=source_type,
        external_id=external_id,
        tickers=(ticker,),
        issuer=f"{ticker} Issuer",
        published_at=published_at,
        title=title,
        document_type=document_type,
        url=url,
        collected_at=datetime(2026, 7, 27, tzinfo=timezone.utc),
        raw_metadata={"generated": True} if generated else {},
    )


class FixtureSECConnector:
    name = "sec"

    def collect(self, request: CollectionRequest) -> List[InformationItem]:
        ticker = request.tickers[0]
        return [
            make_item(
                source=self.name,
                source_type="regulatory_filing",
                external_id=f"fixture-sec-{ticker}",
                ticker=ticker,
                published_at=datetime(2026, 1, 15, tzinfo=timezone.utc),
                title="Fixture SEC filing",
                document_type="8-K",
                url="https://www.sec.gov/example.htm",
            )
        ]


class FailingConnector:
    name = "failing"

    def collect(self, request: CollectionRequest) -> List[InformationItem]:
        raise RuntimeError("fixture source is unavailable")


class HTMLReportTests(unittest.TestCase):
    def test_reads_repository_groups_sorts_and_renders_failures(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            directory = Path(temporary_directory)
            repository = SQLiteInformationRepository(
                directory / "items.sqlite3"
            )
            repository.save(
                [
                    make_item(
                        source="sec",
                        source_type="regulatory_filing",
                        external_id="sec-1",
                        ticker="AAPL",
                        published_at=datetime(
                            2026, 1, 10, tzinfo=timezone.utc
                        ),
                        title="Older SEC filing",
                        document_type="10-Q",
                        url="https://www.sec.gov/item?a=1&b=2",
                    ),
                    make_item(
                        source="mock_community",
                        source_type="community",
                        external_id="community-1",
                        ticker="AAPL",
                        published_at=datetime(
                            2026, 1, 20, tzinfo=timezone.utc
                        ),
                        title="Newer community post",
                        document_type="community_post",
                        url="https://community.example.test/post/1",
                        generated=True,
                    ),
                ]
            )
            output_path = directory / "announcements.html"

            result = generate_html_report(
                repository=repository,
                universe=(
                    UniverseEntry("AAPL", "holdings"),
                    UniverseEntry("EMPTY", "planned"),
                    UniverseEntry("WATCH", "watchlist"),
                ),
                enabled_sources=("sec", "mock_community"),
                start_date=date(2026, 1, 1),
                end_date=date(2026, 1, 31),
                failures=(
                    CollectionFailure(
                        source="sec",
                        ticker="EMPTY",
                        message="HTTP <timeout>",
                    ),
                ),
                output_path=output_path,
            )
            html = output_path.read_text(encoding="utf-8")
            report_exists = output_path.exists()

        self.assertEqual(result.record_count, 2)
        self.assertTrue(report_exists)
        self.assertIn("2026-01-01", html)
        self.assertIn("2026-01-31", html)
        self.assertIn("Holdings", html)
        self.assertIn("Planned", html)
        self.assertIn("Watchlist", html)
        self.assertIn("holdings", html)
        self.assertIn("mock_community", html)
        self.assertIn("Source type", html)
        self.assertIn("Data status", html)
        self.assertIn("regulatory_filing", html)
        self.assertIn("community", html)
        self.assertIn("Demo / generated", html)
        self.assertIn("Demo URL — not live", html)
        self.assertNotIn(
            'href="https://community.example.test/post/1"',
            html,
        )
        self.assertIn("AAPL Issuer", html)
        self.assertIn("10-Q", html)
        self.assertIn("Older SEC filing", html)
        self.assertIn(
            'href="https://www.sec.gov/item?a=1&amp;b=2"',
            html,
        )
        self.assertLess(
            html.index("Newer community post"),
            html.index("Older SEC filing"),
        )
        self.assertIn("No records found for EMPTY", html)
        self.assertIn("No records found for WATCH", html)
        self.assertIn("HTTP &lt;timeout&gt;", html)

    def test_workflow_puts_sec_and_community_in_the_same_report(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            directory = Path(temporary_directory)
            universe_path = directory / "universe.csv"
            universe_path.write_text(
                "ticker,list_type\nAAPL,holdings\n",
                encoding="utf-8",
            )
            settings_path = directory / "settings.yaml"
            settings_path.write_text(
                "enabled_sources:\n"
                "  - sec\n"
                "  - mock_community\n"
                "database_path: data/items.sqlite3\n",
                encoding="utf-8",
            )
            registry = SourceRegistry()
            registry.register("sec", FixtureSECConnector)
            registry.register("mock_community", MockCommunityConnector)
            output_path = directory / "output" / "announcements.html"

            result = run_workflow(
                universe_path=universe_path,
                settings_path=settings_path,
                start_date=date(2026, 1, 1),
                end_date=date(2026, 1, 31),
                output_path=output_path,
                registry=registry,
            )
            html = output_path.read_text(encoding="utf-8")

        self.assertEqual(result.collected_count, 2)
        self.assertEqual(result.save_result.inserted, 2)
        self.assertEqual(result.stored_count, 2)
        self.assertEqual(result.report.record_count, 2)
        self.assertIn("Fixture SEC filing", html)
        self.assertIn("Community announcement for AAPL", html)
        self.assertIn(">sec<", html)
        self.assertIn(">mock_community<", html)
        self.assertIn("Demo / generated", html)
        self.assertIn("Demo URL — not live", html)

    def test_workflow_reports_source_failure_and_still_generates_html(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            directory = Path(temporary_directory)
            universe_path = directory / "universe.csv"
            universe_path.write_text(
                "ticker,list_type\nAAPL,watchlist\n",
                encoding="utf-8",
            )
            settings_path = directory / "settings.yaml"
            settings_path.write_text(
                "enabled_sources:\n"
                "  - failing\n"
                "  - mock_community\n"
                "database_path: data/items.sqlite3\n",
                encoding="utf-8",
            )
            registry = SourceRegistry()
            registry.register("failing", FailingConnector)
            registry.register("mock_community", MockCommunityConnector)
            output_path = directory / "output" / "announcements.html"

            with self.assertLogs(
                "investment_monitor.pipeline", level="ERROR"
            ):
                result = run_workflow(
                    universe_path=universe_path,
                    settings_path=settings_path,
                    start_date=date(2026, 1, 1),
                    end_date=date(2026, 1, 31),
                    output_path=output_path,
                    registry=registry,
            )
            html = output_path.read_text(encoding="utf-8")
            report_exists = output_path.exists()

        self.assertEqual(result.failure_count, 1)
        self.assertEqual(result.report.failure_count, 1)
        self.assertTrue(report_exists)
        self.assertIn("fixture source is unavailable", html)
        self.assertIn("Community announcement for AAPL", html)


if __name__ == "__main__":
    unittest.main()
