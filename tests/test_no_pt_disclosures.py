"""ENP-1 honest-stub disclosure connector tests."""

from datetime import date
import unittest

from investment_monitor.models import CollectionRequest
from investment_monitor.registry import SOURCE_MARKETS, create_default_registry
from investment_monitor.sources.no_pt_disclosures import (
    EuronextLisbonNewsConnector,
    NewswebNoConnector,
)


class NoPtDisclosureTests(unittest.TestCase):
    def test_connectors_are_honest_stubs(self):
        for connector in (
            NewswebNoConnector(),
            EuronextLisbonNewsConnector(),
        ):
            items = connector.collect(CollectionRequest(
                tickers=("X",),
                start_date=date(2026, 8, 1),
                end_date=date(2026, 8, 1),
                markets={"X": "us"},
            ))
            self.assertEqual(items, [])
            self.assertEqual(connector.last_collection_status, "stub")
            self.assertEqual(connector.last_errors, ())

    def test_registry_scopes(self):
        self.assertEqual(SOURCE_MARKETS["newsweb_no"], "no")
        self.assertEqual(SOURCE_MARKETS["euronext_lisbon_news"], "pt")
        registry = create_default_registry()
        self.assertIn("newsweb_no", registry.registered_names)
        self.assertIn("euronext_lisbon_news", registry.registered_names)


if __name__ == "__main__":
    unittest.main()
