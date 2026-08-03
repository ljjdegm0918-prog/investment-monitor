import json
import os
from typing import Any
import unittest
from unittest.mock import patch
from urllib.error import URLError

from investment_monitor import SECClient, SECConfigurationError


class FakeResponse:
    def __init__(self, payload: Any) -> None:
        self._body = json.dumps(payload).encode("utf-8")

    def __enter__(self) -> "FakeResponse":
        return self

    def __exit__(self, *args: Any) -> None:
        return None

    def read(self) -> bytes:
        return self._body


class FakeTime:
    def __init__(self) -> None:
        self.now = 0.0
        self.sleeps = []

    def clock(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now += seconds


class SECClientTests(unittest.TestCase):
    def test_user_agent_is_required_from_the_environment(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaises(SECConfigurationError):
                SECClient.from_environment()

    def test_retries_a_temporary_network_failure(self) -> None:
        calls = []

        def opener(request: Any, timeout: float) -> FakeResponse:
            calls.append((request, timeout))
            if len(calls) == 1:
                raise URLError("temporary failure")
            return FakeResponse({"ok": True})

        fake_time = FakeTime()
        client = SECClient(
            user_agent="InvestmentMonitor/0.1 test@example.com",
            max_retries=1,
            opener=opener,
            clock=fake_time.clock,
            sleeper=fake_time.sleep,
        )

        result = client.get_json("https://data.sec.gov/example.json")

        self.assertEqual(result, {"ok": True})
        self.assertEqual(len(calls), 2)
        self.assertEqual(calls[0][0].get_header("User-agent"), (
            "InvestmentMonitor/0.1 test@example.com"
        ))
        self.assertEqual(calls[0][1], 10.0)

    def test_spaces_requests_at_no_more_than_five_per_second(self) -> None:
        request_times = []
        fake_time = FakeTime()

        def opener(request: Any, timeout: float) -> FakeResponse:
            request_times.append(fake_time.clock())
            return FakeResponse({"ok": True})

        client = SECClient(
            user_agent="InvestmentMonitor/0.1 test@example.com",
            opener=opener,
            clock=fake_time.clock,
            sleeper=fake_time.sleep,
        )

        for index in range(3):
            client.get_json(f"https://data.sec.gov/example-{index}.json")

        self.assertEqual(request_times, [0.0, 0.2, 0.4])


if __name__ == "__main__":
    unittest.main()

