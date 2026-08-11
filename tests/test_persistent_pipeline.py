from datetime import date, datetime, timezone
import logging
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import List
import unittest

from investment_monitor import (
    CollectionPipeline,
    CollectionRequest,
    InformationItem,
    SQLiteInformationRepository,
)


class PartialFailureConnector:
    name = "partial"

    def collect(self, request: CollectionRequest) -> List[InformationItem]:
        ticker = request.tickers[0]
        if ticker == "FAIL":
            raise RuntimeError("fixture source failure")
        if ticker == "EMPTY":
            return []
        now = datetime(2026, 7, 27, tzinfo=timezone.utc)
        return [
            InformationItem(
                source=self.name,
                source_type="fixture",
                external_id=f"item-{ticker}",
                tickers=(ticker,),
                issuer=f"{ticker} Issuer",
                published_at=now,
                title=f"Item for {ticker}",
                document_type="fixture",
                url=f"https://example.test/{ticker}",
                collected_at=now,
                raw_metadata={},
            )
        ]


class HonestEmptyFailureConnector:
    """Connector that cannot collect because required universe data is absent."""

    name = "official-with-universe"

    def __init__(self) -> None:
        self.last_errors = ()

    def collect(self, request: CollectionRequest) -> List[InformationItem]:
        ticker = request.tickers[0]
        self.last_errors = ((ticker, "no_universe_identity"),)
        return []


class PersistentPipelineTests(unittest.TestCase):
    def test_empty_with_connector_error_is_recorded_as_failure(self) -> None:
        logger = logging.getLogger("tests.persistent_pipeline.honest_empty")
        pipeline = CollectionPipeline(
            [HonestEmptyFailureConnector()],
            logger=logger,
        )
        request = CollectionRequest(
            tickers=("SAN",),
            start_date=date(2026, 7, 1),
            end_date=date(2026, 7, 31),
            markets={"SAN": "es"},
        )

        with self.assertLogs(logger, level="ERROR") as captured_logs:
            items = pipeline.collect(request)

        self.assertEqual(items, [])
        self.assertEqual(len(pipeline.last_failures), 1)
        failure = pipeline.last_failures[0]
        self.assertEqual(failure.source, "official-with-universe")
        self.assertEqual(failure.ticker, "SAN")
        self.assertEqual(failure.message, "no_universe_identity")
        self.assertEqual(len(pipeline.last_events), 1)
        event = pipeline.last_events[0]
        self.assertEqual(event.status, "failure")
        self.assertEqual(event.error_message, "no_universe_identity")
        self.assertIn("ticker=SAN status=failure", "\n".join(captured_logs.output))

    def test_partial_failure_does_not_stop_storage_or_other_tickers(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            repository = SQLiteInformationRepository(
                Path(temporary_directory) / "items.sqlite3"
            )
            logger = logging.getLogger("tests.persistent_pipeline")
            pipeline = CollectionPipeline(
                [PartialFailureConnector()],
                repository=repository,
                logger=logger,
            )
            request = CollectionRequest(
                tickers=("GOOD", "EMPTY", "FAIL"),
                start_date=date(2026, 7, 1),
                end_date=date(2026, 7, 31),
            )

            with self.assertLogs(logger, level="INFO") as captured_logs:
                first_items = pipeline.collect(request)
            first_count = repository.count()

            with self.assertLogs(logger, level="INFO"):
                second_items = pipeline.collect(request)
            second_count = repository.count()

        self.assertEqual(len(first_items), 1)
        self.assertEqual(len(second_items), 1)
        self.assertEqual(first_count, 1)
        self.assertEqual(second_count, 1)
        self.assertEqual(pipeline.last_save_result.inserted, 0)
        self.assertEqual(pipeline.last_save_result.updated, 1)
        self.assertEqual(len(pipeline.last_failures), 1)
        self.assertEqual(pipeline.last_failures[0].ticker, "FAIL")
        log_output = "\n".join(captured_logs.output)
        self.assertIn("ticker=GOOD status=success", log_output)
        self.assertIn("ticker=EMPTY status=empty", log_output)
        self.assertIn("ticker=FAIL status=failure", log_output)


if __name__ == "__main__":
    unittest.main()
