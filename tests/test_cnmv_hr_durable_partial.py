"""Durable partial-outcome acceptance tests for the two CNMV HR feeds."""

from datetime import date
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from investment_monitor.application import ConfiguredCollectionResult
from investment_monitor.models import CollectionRequest
from investment_monitor.pipeline import CollectionPipeline
from investment_monitor.sources.cnmv_hr import (
    CnmvHrClient,
    CnmvHrConnector,
    CnmvHrDataError,
    CnmvHrRequestError,
)
from investment_monitor.sqlite_repository import SQLiteInformationRepository
from investment_monitor.web import WebApplication
from investment_monitor.web_repository import WebRepository


FIXTURES = Path(__file__).parent / "fixtures" / "cnmv_hr"
WINDOW_START = date(2026, 8, 1)
WINDOW_END = date(2026, 8, 8)
SAN_UNIVERSE = {
    "SAN": {
        "name": "BANCO SANTANDER, S.A.",
        "exchange": "BME (SIBE)",
        "isin": "ES0113900J37",
    }
}


class FakeResponse:
    def __init__(self, body: bytes) -> None:
        self._body = body

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return None

    def read(self) -> bytes:
        return self._body


class FeedOpener:
    def __init__(self, *, ip, oir) -> None:
        self.responses = {"ip": ip, "oir": oir}
        self.requested = []

    def __call__(self, request, timeout=None):
        self.requested.append(request.full_url)
        feed_id = "oir" if "Otra-Informacion-Relevante" in request.full_url else "ip"
        response = self.responses[feed_id]
        if isinstance(response, Exception):
            raise response
        return FakeResponse(response)


def empty_feed() -> bytes:
    return b'<?xml version="1.0"?><rss version="2.0"><Channel/></rss>'


def three_santander_records() -> bytes:
    body = (FIXTURES / "cnmv_oir.xml").read_bytes()
    return (
        body.replace(b"ACCIONA, S.A.", b"BANCO SANTANDER, S.A.")
        .replace(b"IZERTIS , S.A.", b"BANCO SANTANDER, S.A.")
    )


class CnmvHrDurablePartialTests(unittest.TestCase):
    def _run_scenario(self, *, ip, oir):
        temporary_directory = TemporaryDirectory()
        self.addCleanup(temporary_directory.cleanup)
        project_root = Path(temporary_directory.name)
        (project_root / "config").mkdir()
        (project_root / "data").mkdir()
        (project_root / "config" / "settings.yaml").write_text(
            "enabled_sources:\n  - cnmv_hr\n"
            "database_path: ../data/web.sqlite3\n",
            encoding="utf-8",
        )
        (project_root / "config" / "universe.csv").write_text(
            "ticker,list_type,market\nSAN,holdings,es\n",
            encoding="utf-8",
        )
        database_path = project_root / "data" / "web.sqlite3"
        item_repository = SQLiteInformationRepository(database_path)
        connector = CnmvHrConnector(
            client=CnmvHrClient(
                opener=FeedOpener(ip=ip, oir=oir),
                requests_per_second=1000,
            ),
            universe=SAN_UNIVERSE,
        )
        pipeline = CollectionPipeline((connector,), repository=item_repository)
        items = pipeline.collect(CollectionRequest(
            tickers=("SAN",),
            start_date=WINDOW_START,
            end_date=WINDOW_END,
            markets={"SAN": "es"},
        ))
        WebRepository(
            database_path,
            allowed_sources=("cnmv_hr",),
        ).record_collection_events(pipeline.last_events)
        result = ConfiguredCollectionResult(
            items=tuple(items),
            failures=pipeline.last_failures,
            save_result=pipeline.last_save_result,
            database_path=database_path,
            stored_count=item_repository.count(),
            events=pipeline.last_events,
        )
        application = WebApplication(
            project_root,
            collection_runner=lambda **kwargs: result,
        )
        summary = application.collect_tickers(
            ("SAN",),
            lookback_days=30,
            today=WINDOW_END,
            markets={"SAN": "es"},
        )
        return database_path, connector, pipeline, items, summary

    def _assert_durable_partial(self, *, ip, oir, failed_feed: str) -> None:
        database_path, connector, pipeline, items, summary = self._run_scenario(
            ip=ip,
            oir=oir,
        )

        self.assertEqual(len(items), 3)
        self.assertEqual(pipeline.last_save_result.inserted, 3)
        self.assertEqual(len(connector.last_errors), 1)
        self.assertIn(failed_feed, connector.last_errors[0][1].lower())
        self.assertEqual(len(pipeline.last_failures), 1)
        self.assertEqual(pipeline.last_failures[0].source, "cnmv_hr")
        self.assertEqual(pipeline.last_failures[0].ticker, "SAN")
        self.assertIn(failed_feed, pipeline.last_failures[0].message.lower())
        self.assertEqual(len(pipeline.last_events), 1)
        event = pipeline.last_events[0]
        self.assertEqual(event.status, "partial")
        self.assertEqual(event.records_read, 3)
        self.assertEqual(event.records_inserted, 3)
        self.assertIn(failed_feed, (event.error_message or "").lower())
        self.assertEqual(summary["status"], "partial")
        self.assertEqual(summary["records_fetched"], 3)
        self.assertEqual(summary["failures"][0]["source"], "cnmv_hr")
        self.assertIn(failed_feed, summary["failures"][0]["message"].lower())

        # Both information and truthful partial activity survive a restart.
        reopened_items = SQLiteInformationRepository(database_path).query(
            ticker="SAN",
            source="cnmv_hr",
        )
        reopened_activity = WebRepository(
            database_path,
            allowed_sources=("cnmv_hr",),
        ).activity(source="cnmv_hr", status="partial")
        self.assertEqual(len(reopened_items), 3)
        self.assertEqual(len(reopened_activity["runs"]), 1)
        self.assertEqual(len(reopened_activity["logs"]), 1)
        self.assertEqual(reopened_activity["runs"][0]["status"], "partial")
        self.assertEqual(reopened_activity["runs"][0]["records_fetched"], 3)
        self.assertIn(
            failed_feed,
            (reopened_activity["runs"][0]["error_summary"] or "").lower(),
        )
        self.assertEqual(reopened_activity["logs"][0]["status"], "partial")
        self.assertIn(
            failed_feed,
            (reopened_activity["logs"][0]["error_message"] or "").lower(),
        )

    def test_ip_three_records_oir_failure_is_durable_partial(self) -> None:
        self._assert_durable_partial(
            ip=three_santander_records(),
            oir=CnmvHrRequestError("oir fixture blocked"),
            failed_feed="oir",
        )

    def test_oir_three_records_ip_failure_is_durable_partial(self) -> None:
        self._assert_durable_partial(
            ip=CnmvHrDataError("ip malformed fixture"),
            oir=three_santander_records(),
            failed_feed="ip",
        )

    def test_empty_success_plus_failure_is_partial(self) -> None:
        _, connector, pipeline, items, summary = self._run_scenario(
            ip=empty_feed(),
            oir=CnmvHrRequestError("oir fixture blocked"),
        )

        self.assertEqual(items, [])
        self.assertEqual(pipeline.last_events[0].status, "partial")
        self.assertEqual(len(pipeline.last_failures), 1)
        self.assertIn("oir", connector.last_errors[0][1].lower())
        self.assertEqual(summary["status"], "partial")

    def test_two_empty_feeds_are_empty(self) -> None:
        database_path, connector, pipeline, items, summary = self._run_scenario(
            ip=empty_feed(),
            oir=empty_feed(),
        )

        self.assertEqual(items, [])
        self.assertEqual(connector.last_errors, ())
        self.assertEqual(pipeline.last_failures, ())
        self.assertEqual(pipeline.last_events[0].status, "empty")
        self.assertEqual(summary["status"], "empty")
        activity = WebRepository(database_path).activity(
            source="cnmv_hr", status="empty"
        )
        self.assertEqual(activity["runs"][0]["status"], "empty")
        self.assertEqual(activity["logs"][0]["status"], "empty")

    def test_two_failed_feeds_are_failure(self) -> None:
        database_path, connector, pipeline, items, summary = self._run_scenario(
            ip=CnmvHrRequestError("ip fixture blocked"),
            oir=CnmvHrDataError("oir malformed fixture"),
        )

        self.assertEqual(items, [])
        self.assertEqual(pipeline.last_events[0].status, "failure")
        self.assertEqual(len(pipeline.last_failures), 1)
        error = pipeline.last_failures[0].message.lower()
        self.assertIn("ip", error)
        self.assertIn("oir", error)
        self.assertEqual(summary["status"], "failure")
        activity = WebRepository(database_path).activity(
            source="cnmv_hr", status="failure"
        )
        self.assertEqual(activity["runs"][0]["status"], "failure")
        self.assertEqual(activity["logs"][0]["status"], "failure")
        self.assertIn("ip", (activity["logs"][0]["error_message"] or "").lower())
        self.assertIn("oir", (activity["logs"][0]["error_message"] or "").lower())


if __name__ == "__main__":
    unittest.main()
