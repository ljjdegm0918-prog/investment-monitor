"""Offline contract tests for the explicit Canadian EDGAR fallback."""

from __future__ import annotations

import json
import os
from datetime import date
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from investment_monitor.connectors.base import ConnectorUnavailableError
from investment_monitor.models import CollectionRequest
from investment_monitor.sources.ca_edgar import (
    IDENTITY_SCHEMA,
    CaEdgarConnector,
    CaEdgarDataError,
    CaEdgarIdentity,
    load_identities_from_path,
)
from investment_monitor.sources.sec.connector import ARCHIVES_BASE_URL, SUBMISSIONS_BASE_URL


FIXTURES = Path(__file__).parent / "fixtures" / "ca_edgar"
CIK = 1594805
DIRECTORY = f"{ARCHIVES_BASE_URL}/{CIK}"


def fixture(name: str):
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def submission_url() -> str:
    return f"{SUBMISSIONS_BASE_URL}/CIK{CIK:010d}.json"


def index_url(accession_without_dashes: str) -> str:
    return f"{DIRECTORY}/{accession_without_dashes}/index.json"


class FixtureClient:
    def __init__(self, responses):
        self.responses = dict(responses)
        self.urls = []

    def get_json(self, url):
        self.urls.append(url)
        value = self.responses[url]
        if isinstance(value, Exception):
            raise value
        return value


def shop_identity() -> CaEdgarIdentity:
    return CaEdgarIdentity(
        ca_ticker="SHOP.TO",
        exchange="TSX",
        us_ticker="SHOP",
        cik=CIK,
        issuer="Shopify Inc.",
        mapping_source="reviewed_ca_crosslist_fixture",
        mapping_version="2026-08-22",
    )


def normal_responses():
    return {
        submission_url(): fixture("CIK0001594805.json"),
        f"{SUBMISSIONS_BASE_URL}/CIK0001594805-submissions-001.json": fixture(
            "CIK0001594805-submissions-001.json"
        ),
        index_url("000159480526000003"): fixture("index_000159480526000003.json"),
        index_url("000159480526000002"): fixture("index_000159480526000002.json"),
        index_url("000159480526000000"): fixture("index_000159480526000000.json"),
        index_url("000159480525000010"): fixture("index_000159480525000010.json"),
    }


class CaEdgarConnectorTests(unittest.TestCase):
    def test_configuration_error_requires_sec_identity_and_mapping_path(self):
        with patch.dict(os.environ, {}, clear=True):
            self.assertIn("SEC_USER_AGENT", CaEdgarConnector.configuration_error())
        with patch.dict(os.environ, {"SEC_USER_AGENT": "agent contact@example.test"}, clear=True):
            self.assertIn("CA_EDGAR_IDENTITY_PATH", CaEdgarConnector.configuration_error())

    def test_environment_loader_requires_valid_mapping_file(self):
        with TemporaryDirectory() as temporary_directory:
            path = Path(temporary_directory) / "identities.json"
            path.write_text(json.dumps({
                "schema": IDENTITY_SCHEMA,
                "identities": [{
                    "ca_ticker": "SHOP.TO", "exchange": "TSX",
                    "us_ticker": "SHOP", "cik": CIK,
                    "issuer": "Shopify Inc.",
                }],
            }), encoding="utf-8")
            loaded = load_identities_from_path(path)
            self.assertEqual(loaded, (CaEdgarIdentity("SHOP", "TSX", "SHOP", CIK, "Shopify Inc."),))
            with patch.dict(os.environ, {
                "SEC_USER_AGENT": "agent contact@example.test",
                "CA_EDGAR_IDENTITY_PATH": str(path),
            }, clear=True):
                connector = CaEdgarConnector.from_environment()

        self.assertEqual(connector._identities, loaded)

    def test_environment_loader_rejects_schema_drift_as_unavailable(self):
        with TemporaryDirectory() as temporary_directory:
            path = Path(temporary_directory) / "identities.json"
            path.write_text(json.dumps({"schema": IDENTITY_SCHEMA, "identities": [], "extra": True}), encoding="utf-8")
            with self.assertRaisesRegex(CaEdgarDataError, "exactly"):
                load_identities_from_path(path)
            with patch.dict(os.environ, {
                "SEC_USER_AGENT": "agent contact@example.test",
                "CA_EDGAR_IDENTITY_PATH": str(path),
            }, clear=True):
                with self.assertRaises(ConnectorUnavailableError):
                    CaEdgarConnector.from_environment()

    def test_collects_only_allowed_forms_with_official_urls_and_attachments(self):
        client = FixtureClient(normal_responses())
        connector = CaEdgarConnector(client=client, identities=(shop_identity(),))

        items = connector.collect(CollectionRequest(
            tickers=("SHOP.TO",),
            start_date=date(2026, 8, 1),
            end_date=date(2026, 8, 4),
            markets={"SHOP.TO": "ca"},
        ))

        self.assertEqual(
            [item.document_type for item in items],
            ["annual_report", "material_change", "material_change"],
        )
        self.assertEqual(
            [item.raw_metadata["sec_form"] for item in items],
            ["40-F", "6-K", "8-K/A"],
        )
        annual = items[0]
        self.assertEqual(annual.source, "ca_edgar")
        self.assertEqual(annual.source_type, "regulatory_filing")
        self.assertEqual(annual.market, "ca")
        self.assertEqual(annual.tickers, ("SHOP",))
        self.assertEqual(annual.external_id, "sec:0001594805:0001594805-26-000003")
        self.assertEqual(
            annual.url,
            f"{DIRECTORY}/000159480526000003/annual.htm",
        )
        metadata = annual.raw_metadata
        self.assertEqual(metadata["source_tier"], 1)
        self.assertEqual(metadata["source_tier_label"], "us_regulator")
        self.assertTrue(metadata["non_sedar"])
        self.assertEqual(metadata["official_source_id"], "0001594805-26-000003")
        self.assertEqual(
            metadata["accession_url"],
            f"{DIRECTORY}/000159480526000003/0001594805-26-000003-index.html",
        )
        self.assertEqual(metadata["document_url"], annual.url)
        self.assertEqual(metadata["index_url"], index_url("000159480526000003"))
        self.assertEqual(metadata["attachments"], [
            annual.url,
            f"{DIRECTORY}/000159480526000003/exhibit99.pdf",
        ])
        self.assertEqual(metadata["mapping_version"], "2026-08-22")
        self.assertEqual(connector.last_collection_status, "success")
        self.assertEqual(connector.last_errors, ())
        self.assertNotIn(index_url("000159480526000001"), client.urls)

    def test_loads_overlapping_historical_submissions(self):
        connector = CaEdgarConnector(
            client=FixtureClient(normal_responses()), identities=(shop_identity(),)
        )

        items = connector.collect(CollectionRequest(
            tickers=("SHOP",),
            start_date=date(2025, 6, 30), end_date=date(2025, 6, 30),
            markets={"SHOP": "ca"},
        ))

        self.assertEqual(len(items), 1)
        self.assertEqual(items[0].document_type, "annual_report")
        self.assertEqual(items[0].raw_metadata["sec_form"], "20-F/A")
        self.assertEqual(items[0].raw_metadata["revision_semantics"], "amendment")

    def test_missing_mapping_is_failure_not_empty_and_preserves_successful_ticker(self):
        connector = CaEdgarConnector(
            client=FixtureClient(normal_responses()), identities=(shop_identity(),)
        )

        items = connector.collect(CollectionRequest(
            tickers=("SHOP", "MISSING"),
            start_date=date(2026, 8, 4), end_date=date(2026, 8, 4),
            markets={"SHOP": "ca", "MISSING": "ca"},
        ))

        self.assertEqual(len(items), 1)
        self.assertEqual(connector.last_collection_status, "partial")
        self.assertEqual(connector.last_errors[0].ticker, "MISSING")
        self.assertIn("No explicit", connector.last_errors[0].message)

    def test_conflicting_mapping_fails_closed_before_request(self):
        client = FixtureClient({})
        connector = CaEdgarConnector(client=client, identities=(
            shop_identity(),
            CaEdgarIdentity("SHOP", "TSXV", "SHOP", CIK),
        ))

        items = connector.collect(CollectionRequest(
            tickers=("SHOP",),
            start_date=date(2026, 8, 4), end_date=date(2026, 8, 4),
            markets={"SHOP": "ca"},
        ))

        self.assertEqual(items, [])
        self.assertEqual(connector.last_collection_status, "unavailable")
        self.assertIn("Conflicting", connector.last_errors[0].message)
        self.assertEqual(client.urls, [])

    def test_mapping_with_wrong_us_ticker_fails_closed(self):
        connector = CaEdgarConnector(
            client=FixtureClient(normal_responses()),
            identities=(CaEdgarIdentity("SHOP", "TSX", "WRONG", CIK),),
        )

        items = connector.collect(CollectionRequest(
            tickers=("SHOP",),
            start_date=date(2026, 8, 4), end_date=date(2026, 8, 4),
            markets={"SHOP": "ca"},
        ))

        self.assertEqual(items, [])
        self.assertEqual(connector.last_collection_status, "unavailable")
        self.assertIn("disagrees", connector.last_errors[0].message)

    def test_malformed_attachment_index_fails_ticker_not_as_empty(self):
        responses = normal_responses()
        responses[index_url("000159480526000003")] = {"directory": {"item": []}}
        connector = CaEdgarConnector(
            client=FixtureClient(responses), identities=(shop_identity(),)
        )

        items = connector.collect(CollectionRequest(
            tickers=("SHOP",),
            start_date=date(2026, 8, 4), end_date=date(2026, 8, 4),
            markets={"SHOP": "ca"},
        ))

        self.assertEqual(items, [])
        self.assertEqual(connector.last_collection_status, "unavailable")
        self.assertIn("attachment", connector.last_errors[0].message)

    def test_window_with_no_allowed_form_is_honest_empty(self):
        connector = CaEdgarConnector(
            client=FixtureClient(normal_responses()), identities=(shop_identity(),)
        )

        items = connector.collect(CollectionRequest(
            tickers=("SHOP",),
            start_date=date(2026, 8, 2), end_date=date(2026, 8, 2),
            markets={"SHOP": "ca"},
        ))

        self.assertEqual(items, [])
        self.assertEqual(connector.last_collection_status, "empty")
        self.assertEqual(connector.last_errors, ())

    def test_exchange_suffix_selects_one_of_multiple_reviewed_mappings(self):
        connector = CaEdgarConnector(
            client=FixtureClient(normal_responses()),
            identities=(
                shop_identity(),
                CaEdgarIdentity("SHOP", "TSXV", "SHOP", CIK),
            ),
        )
        items = connector.collect(CollectionRequest(
            tickers=("SHOP.TO",),
            start_date=date(2026, 8, 4), end_date=date(2026, 8, 4),
            markets={"SHOP.TO": "ca"},
        ))
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0].raw_metadata["exchange"], "TSX")


if __name__ == "__main__":
    unittest.main()
