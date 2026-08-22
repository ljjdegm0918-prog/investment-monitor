from __future__ import annotations

import unittest
from datetime import date
from unittest.mock import patch

from investment_monitor.models import CollectionRequest
from investment_monitor.registry import create_default_registry
from investment_monitor.sources.ceoca_sedar import (
    CeocaSedarConnector,
    parse_ceoca_sedar_spiels,
)

VALID = {
    "channel": "sedar",
    "name": "SEDAR bot",
    "bot": "sedi",
    "spiel_id": "filing-1",
    "timestamp": 1786708800000,
    "spiel": (
        "#sedar $AGMR Silver Mountain Resources Inc. just filed a new SEDAR document:\n\n"
        "Interim MD&A - English\n"
        "https://ceo.ca/content/sedar/AGMR-2026-08-14-interim-mda-english-8e8f.pdf"
    ),
}


class CeocaSedarTests(unittest.TestCase):
    def test_parser_accepts_only_exact_bot_pdf(self) -> None:
        rows = parse_ceoca_sedar_spiels([VALID])
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].ticker, "AGMR")
        self.assertEqual(rows[0].document, "Interim MD&A - English")

        for mutation in (
            {**VALID, "channel": "agmr"},
            {**VALID, "name": "someone"},
            {**VALID, "bot": "user"},
            {**VALID, "spiel": VALID["spiel"].replace("https://ceo.ca/", "https://evil.example/")},
        ):
            self.assertEqual(parse_ceoca_sedar_spiels([mutation]), [])

    def test_connector_maps_partial_third_party_filing(self) -> None:
        company_channel_row = {**VALID, "channel": "agmr"}
        connector = CeocaSedarConnector(
            fetch_json=lambda channel, user_agent, until: {
                "spiels": [company_channel_row]
            }
        )
        request = CollectionRequest(
            tickers=("AGMR.V",),
            start_date=date(2026, 8, 14),
            end_date=date(2026, 8, 14),
            markets={"AGMR": "ca"},
        )
        items = connector.collect(request)
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0].source, "ceoca_sedar")
        self.assertEqual(items[0].source_type, "regulatory_filing")
        self.assertEqual(items[0].tickers, ("AGMR",))
        self.assertEqual(items[0].raw_metadata["source_tier"], 4)
        self.assertFalse(items[0].raw_metadata["is_official"])
        self.assertEqual(connector.status, "partial")
        self.assertEqual(connector.last_collection_status, "partial")

    def test_connector_fetches_company_channel_not_global_sedar(self) -> None:
        calls = []
        company_channel_row = {**VALID, "channel": "agmr"}

        def fetch(channel, user_agent, until):
            calls.append(channel)
            return {"spiels": [company_channel_row]}

        connector = CeocaSedarConnector(fetch_json=fetch)
        connector.collect(CollectionRequest(
            tickers=("AGMR",),
            start_date=date(2026, 8, 14),
            end_date=date(2026, 8, 14),
            markets={"AGMR": "ca"},
        ))
        self.assertEqual(calls, ["agmr"])

    def test_multi_ticker_pagination_cap_keeps_verified_partial_results(self) -> None:
        good = {
            **VALID,
            "channel": "good",
            "spiel_id": "good-1",
            "spiel": VALID["spiel"].replace("AGMR", "GOOD"),
        }

        def fetch(channel, user_agent, until):
            if channel == "good":
                return {"spiels": [good]}
            page_timestamp = 1786708800000 if until is None else 1786622400000
            return {"spiels": [
                {
                    **VALID,
                    "channel": "bad",
                    "spiel_id": f"bad-{index}-{page_timestamp}",
                    "timestamp": page_timestamp - index,
                }
                for index in range(50)
            ]}

        connector = CeocaSedarConnector(fetch_json=fetch)
        with patch(
            "investment_monitor.sources.ceoca_sedar.connector.MAX_PAGES_PER_TICKER",
            2,
        ):
            items = connector.collect(CollectionRequest(
                tickers=("GOOD", "BAD"),
                start_date=date(2026, 8, 1),
                end_date=date(2026, 8, 14),
                markets={"GOOD": "ca", "BAD": "ca"},
            ))

        self.assertEqual([item.tickers for item in items], [("GOOD",)])
        self.assertEqual(connector.last_errors[0][0], "BAD")
        self.assertIn("pagination cap", connector.last_errors[0][1])
        self.assertEqual(connector.last_collection_status, "partial")

    def test_empty_company_channel_is_successful_exhaustion(self) -> None:
        connector = CeocaSedarConnector(
            fetch_json=lambda channel, user_agent, until: {"spiels": []}
        )
        items = connector.collect(CollectionRequest(
            tickers=("EMPTY",),
            start_date=date(2026, 8, 14),
            end_date=date(2026, 8, 14),
            markets={"EMPTY": "ca"},
        ))
        self.assertEqual(items, [])
        self.assertEqual(connector.last_errors, ())
        self.assertEqual(connector.last_collection_status, "empty")

    def test_full_page_followed_by_empty_page_is_successful_exhaustion(self) -> None:
        calls = {"count": 0}

        def fetch(channel, user_agent, until):
            calls["count"] += 1
            if calls["count"] > 1:
                return {"spiels": []}
            return {"spiels": [
                {
                    **VALID,
                    "channel": "agmr",
                    "spiel_id": f"agmr-{index}",
                    "timestamp": 1786708800000 - index,
                }
                for index in range(50)
            ]}

        connector = CeocaSedarConnector(fetch_json=fetch)
        items = connector.collect(CollectionRequest(
            tickers=("AGMR",),
            start_date=date(2026, 8, 1),
            end_date=date(2026, 8, 14),
            markets={"AGMR": "ca"},
        ))
        self.assertEqual(len(items), 50)
        self.assertEqual(calls["count"], 2)
        self.assertEqual(connector.last_errors, ())

    def test_registry_registers_connector(self) -> None:
        registry = create_default_registry()
        connector = registry.factory_for("ceoca_sedar")()
        self.assertEqual(connector.status, "partial")


if __name__ == "__main__":
    unittest.main()
