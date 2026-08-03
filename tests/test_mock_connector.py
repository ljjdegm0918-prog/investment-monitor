from datetime import date, timezone
import unittest

from investment_monitor import CollectionRequest, MockConnector


class MockConnectorTests(unittest.TestCase):
    def test_returns_one_standardized_item_per_ticker(self) -> None:
        request = CollectionRequest(
            tickers=("aapl", "MSFT"),
            start_date=date(2026, 1, 1),
            end_date=date(2026, 1, 31),
        )

        items = MockConnector().collect(request)

        self.assertEqual(len(items), 2)
        self.assertEqual(items[0].source, "mock")
        self.assertEqual(items[0].tickers, ("AAPL",))
        self.assertEqual(items[1].tickers, ("MSFT",))
        self.assertEqual(items[0].published_at.tzinfo, timezone.utc)

    def test_request_rejects_an_invalid_date_range(self) -> None:
        with self.assertRaises(ValueError):
            CollectionRequest(
                tickers=("AAPL",),
                start_date=date(2026, 2, 1),
                end_date=date(2026, 1, 1),
            )


if __name__ == "__main__":
    unittest.main()

