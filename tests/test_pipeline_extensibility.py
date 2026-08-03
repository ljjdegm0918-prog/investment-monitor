from datetime import date, datetime, timezone
from typing import List
import unittest

from investment_monitor import (
    CollectionPipeline,
    CollectionRequest,
    InformationItem,
    SourceRegistry,
)


class TestConnector:
    """A second connector used to prove the pipeline is source-independent."""

    name = "test-community"

    def collect(self, request: CollectionRequest) -> List[InformationItem]:
        now = datetime.now(timezone.utc)
        return [
            InformationItem(
                source=self.name,
                source_type="community",
                external_id="community-1",
                tickers=request.tickers,
                issuer="Example Issuer",
                published_at=now,
                title="A community post",
                document_type="post",
                url="https://example.test/community/1",
                collected_at=now,
                raw_metadata={"score": 10},
            )
        ]


class PipelineExtensibilityTests(unittest.TestCase):
    def setUp(self) -> None:
        self.request = CollectionRequest(
            tickers=("AAPL",),
            start_date=date(2026, 1, 1),
            end_date=date(2026, 1, 31),
        )

    def test_registered_mock_connector_is_loaded_and_used(self) -> None:
        from investment_monitor import MockConnector

        registry = SourceRegistry()
        registry.register("mock", MockConnector)

        pipeline = CollectionPipeline(registry.load_enabled(["mock"]))
        items = pipeline.collect(self.request)

        self.assertEqual([item.source for item in items], ["mock"])

    def test_new_connector_works_without_pipeline_changes(self) -> None:
        registry = SourceRegistry()
        registry.register(TestConnector.name, TestConnector)

        pipeline = CollectionPipeline(
            registry.load_enabled([TestConnector.name])
        )
        items = pipeline.collect(self.request)

        self.assertEqual(len(items), 1)
        self.assertEqual(items[0].source, "test-community")
        self.assertEqual(items[0].source_type, "community")


if __name__ == "__main__":
    unittest.main()
