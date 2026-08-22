"""Shared transport retry tests for official public disclosure clients."""

from io import BytesIO
import unittest
from unittest.mock import patch
from urllib.error import HTTPError, URLError

from investment_monitor.sources._public_disclosure import (
    PublicDisclosureError,
    fetch_text,
)


class FakeResponse:
    headers = {"Content-Type": "text/html"}

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return None

    def read(self):
        return b"official payload"


class PublicDisclosureTransportTests(unittest.TestCase):
    def test_retries_temporary_transport_failure_with_bounded_backoff(self) -> None:
        sleeps = []
        with patch(
            "investment_monitor.sources._public_disclosure.urlopen",
            side_effect=[URLError("temporary"), FakeResponse()],
        ) as opener:
            text, _ = fetch_text(
                "https://official.example/feed", sleeper=sleeps.append
            )
        self.assertEqual(text, "official payload")
        self.assertEqual(opener.call_count, 2)
        self.assertEqual(sleeps, [0.5])

    def test_does_not_retry_non_retryable_http_error(self) -> None:
        error = HTTPError(
            "https://official.example/feed", 403, "Forbidden", {}, BytesIO(b"denied")
        )
        with patch(
            "investment_monitor.sources._public_disclosure.urlopen",
            side_effect=error,
        ) as opener:
            with self.assertRaisesRegex(PublicDisclosureError, "HTTP 403"):
                fetch_text("https://official.example/feed", sleeper=lambda _delay: None)
        self.assertEqual(opener.call_count, 1)


if __name__ == "__main__":
    unittest.main()
