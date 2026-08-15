"""Per-source circuit breaker unit tests for CollectionPipeline.

FakeConnector 通过抛异常模拟 timeout/请求失败，不依赖真实网络。
"""

from datetime import date, datetime, timezone
from typing import List
import unittest

from investment_monitor import (
    CollectionPipeline,
    CollectionRequest,
    InformationItem,
)


class FailingConnector:
    """A connector that raises for configured tickers and succeeds otherwise."""

    name = "fake-source"

    def __init__(self, fail_tickers) -> None:
        self.calls: List[str] = []
        self._fail = set(fail_tickers)

    def collect(self, request: CollectionRequest) -> List[InformationItem]:
        ticker = request.tickers[0]
        self.calls.append(ticker)
        if ticker in self._fail:
            raise RuntimeError(f"{ticker} timed out")
        now = datetime.now(timezone.utc)
        return [
            InformationItem(
                source=self.name,
                source_type="news",
                external_id=f"item-{ticker}",
                tickers=(ticker,),
                issuer=f"Issuer {ticker}",
                published_at=now,
                title=f"Title {ticker}",
                document_type="news",
                url=f"https://example.test/{ticker}",
                collected_at=now,
            )
        ]


class CollectionCircuitTests(unittest.TestCase):
    def setUp(self) -> None:
        self.start_date = date(2026, 1, 1)
        self.end_date = date(2026, 1, 31)

    def _request(self, tickers):
        return CollectionRequest(
            tickers=tuple(tickers),
            start_date=self.start_date,
            end_date=self.end_date,
        )

    def test_circuit_breaker_skips_remaining_tickers_after_two_failures(self) -> None:
        connector = FailingConnector(fail_tickers={"FAIL1", "FAIL2"})
        pipeline = CollectionPipeline([connector])

        items = pipeline.collect(self._request(("FAIL1", "FAIL2", "SKIP1", "SKIP2")))

        # 前两个 ticker 真正调用了 collect，第三个起被熔断跳过。
        self.assertEqual(connector.calls, ["FAIL1", "FAIL2"])
        self.assertEqual(items, [])
        messages = [failure.message for failure in pipeline.last_failures]
        self.assertTrue(any("circuit_open" in message for message in messages))
        # 2 次真实失败 + 2 次 circuit_open 跳过。
        self.assertEqual(len(pipeline.last_failures), 4)
        self.assertEqual(
            [event.status for event in pipeline.last_events],
            ["failure", "failure", "failure", "failure"],
        )

    def test_circuit_breaker_success_resets_failure_count(self) -> None:
        connector = FailingConnector(fail_tickers={"FAIL1", "FAIL2"})
        pipeline = CollectionPipeline([connector])

        items = pipeline.collect(
            self._request(("FAIL1", "OK1", "FAIL2", "OK2"))
        )

        # 每次失败后紧跟一次成功，计数被重置，故不熔断、4 个 ticker 都 collect。
        self.assertEqual(connector.calls, ["FAIL1", "OK1", "FAIL2", "OK2"])
        self.assertEqual([item.external_id for item in items], ["item-OK1", "item-OK2"])
        self.assertFalse(any(
            "circuit_open" in failure.message
            for failure in pipeline.last_failures
        ))
        self.assertEqual(len(pipeline.last_failures), 2)

    def test_circuit_breaker_mixed_outcome_is_partial(self) -> None:
        connector = FailingConnector(fail_tickers={"FAIL1", "FAIL2"})
        pipeline = CollectionPipeline([connector])

        items = pipeline.collect(
            self._request(("OK", "FAIL1", "FAIL2", "SKIP"))
        )

        # OK 成功，FAIL1/FAIL2 连续失败触发熔断，SKIP 被跳过。
        self.assertEqual(connector.calls, ["OK", "FAIL1", "FAIL2"])
        self.assertEqual(len(items), 1)
        messages = [failure.message for failure in pipeline.last_failures]
        self.assertTrue(any("circuit_open" in message for message in messages))
        self.assertEqual(len(pipeline.last_failures), 3)
        statuses = [event.status for event in pipeline.last_events]
        self.assertIn("success", statuses)
        self.assertIn("failure", statuses)


if __name__ == "__main__":
    unittest.main()
