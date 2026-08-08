"""Optional minimal live EDINET API validation; disabled by default."""

from datetime import datetime, timedelta, timezone
import os
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from investment_monitor.sources.edinet import EDINETClient, EDINETConnector, EDINETStore


@unittest.skipUnless(
    os.environ.get("RUN_EDINET_LIVE_TEST") == "1" and os.environ.get("EDINET_API_KEY"),
    "Set RUN_EDINET_LIVE_TEST=1 and EDINET_API_KEY to run the live EDINET test.",
)
class EDINETLiveIntegrationTests(unittest.TestCase):
    def test_official_recent_list_request(self) -> None:
        with TemporaryDirectory() as directory:
            now = datetime.now(timezone.utc)
            connector = EDINETConnector(
                EDINETClient.from_environment(),
                EDINETStore(Path(directory) / "edinet-live.sqlite3"),
                now=lambda: now,
            )
            result = connector.getWatchlistDisclosuresSince(
                companies=[{"edinetCode": "E02144"}],
                since=now - timedelta(hours=24),
                now=now,
            )
            self.assertFalse(result.partial, result.errors)
            self.assertTrue(all(item.doc_id for item in result.items))


if __name__ == "__main__":
    unittest.main()