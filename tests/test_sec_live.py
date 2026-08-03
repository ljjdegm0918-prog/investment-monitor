from datetime import date, timedelta
import os
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from investment_monitor import CollectionRequest, SECClient, SECConnector
from investment_monitor.sources.sec import TickerCIKResolver


@unittest.skipUnless(
    os.environ.get("RUN_SEC_LIVE_TEST") == "1"
    and bool(os.environ.get("SEC_USER_AGENT")),
    "Set RUN_SEC_LIVE_TEST=1 and SEC_USER_AGENT to run the live SEC test.",
)
class SECLiveIntegrationTests(unittest.TestCase):
    def test_collects_recent_aapl_filings(self) -> None:
        end_date = date.today()
        start_date = end_date - timedelta(days=365)

        with TemporaryDirectory() as temporary_directory:
            client = SECClient.from_environment()
            resolver = TickerCIKResolver(
                client=client,
                cache_path=Path(temporary_directory) / "tickers.json",
            )
            connector = SECConnector(client=client, resolver=resolver)
            items = connector.collect(
                CollectionRequest(
                    tickers=("AAPL",),
                    start_date=start_date,
                    end_date=end_date,
                )
            )

        self.assertGreater(len(items), 0)
        self.assertEqual(connector.last_errors, ())
        self.assertTrue(all(item.source == "sec" for item in items))


if __name__ == "__main__":
    unittest.main()
