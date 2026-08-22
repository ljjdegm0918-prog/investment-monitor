"""Offline contract tests for the explicitly mapped Singapore EDGAR fallback."""

from __future__ import annotations

import json
import os
from datetime import date
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

import pytest

from investment_monitor.models import CollectionRequest
from investment_monitor.sources.sec.connector import ARCHIVES_BASE_URL, SUBMISSIONS_BASE_URL
from investment_monitor.sources.sg_edgar import IDENTITY_SCHEMA, SgEdgarConnector, SgEdgarDataError, SgEdgarIdentity, load_identities_from_path


FIXTURES = Path(__file__).parent / "fixtures" / "sg_edgar"
CIK = 1234
DIRECTORY = f"{ARCHIVES_BASE_URL}/{CIK}"


def fixture(name: str):
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


class Client:
    def __init__(self, responses):
        self.responses = responses
        self.urls = []

    def get_json(self, url):
        self.urls.append(url)
        return self.responses[url]


def identity():
    return SgEdgarIdentity("Y92.SI", "SGX Mainboard", "SE", CIK, "Sea Limited", "reviewed_sg_fixture", "2026-08-22")


def responses():
    return {
        f"{SUBMISSIONS_BASE_URL}/CIK{CIK:010d}.json": fixture("CIK0000001234.json"),
        f"{SUBMISSIONS_BASE_URL}/CIK0000001234-submissions-001.json": fixture("CIK0000001234-submissions-001.json"),
        f"{DIRECTORY}/000000123426000001/index.json": fixture("index_000000123426000001.json"),
        f"{DIRECTORY}/000000123425000003/index.json": fixture("index_000000123425000003.json"),
    }


def request(*tickers: str, start=date(2026, 8, 5), end=date(2026, 8, 5)):
    return CollectionRequest(tickers=tickers, start_date=start, end_date=end, markets={ticker: "sg" for ticker in tickers})


def test_requires_reviewed_mapping_and_sec_user_agent():
    with patch.dict(os.environ, {}, clear=True):
        assert "SEC_USER_AGENT" in SgEdgarConnector.configuration_error()
    with TemporaryDirectory() as tmp:
        path = Path(tmp) / "map.json"
        path.write_text(json.dumps({"schema": IDENTITY_SCHEMA, "identities": [{"sg_ticker": "Y92", "exchange": "SGX Mainboard", "us_ticker": "SE", "cik": CIK}]}), encoding="utf-8")
        assert load_identities_from_path(path)[0].sg_ticker == "Y92"
        with patch.dict(os.environ, {"SEC_USER_AGENT": "test contact@example.test", "SG_EDGAR_IDENTITY_PATH": str(path)}, clear=True):
            assert SgEdgarConnector.configuration_error() is None


def test_collects_us_regulatory_fallback_with_attachment_index():
    connector = SgEdgarConnector(client=Client(responses()), identities=(identity(),))
    items = connector.collect(request("Y92.SI"))
    assert len(items) == 1
    item = items[0]
    assert item.market == "sg" and item.source == "sg_edgar" and item.document_type == "financial_results"
    assert item.tickers == ("Y92",)
    assert item.raw_metadata["source_tier"] == 1
    assert item.raw_metadata["source_name"] == "sec"
    assert item.raw_metadata["is_sgx_announcement"] is False
    assert item.raw_metadata["attachments"] == [f"{DIRECTORY}/000000123426000001/earnings.htm", f"{DIRECTORY}/000000123426000001/exhibit99.pdf"]
    assert connector.last_collection_status == "success"


def test_historical_submissions_and_amendments_are_included():
    connector = SgEdgarConnector(client=Client(responses()), identities=(identity(),))
    items = connector.collect(request("Y92", start=date(2025, 6, 30), end=date(2025, 6, 30)))
    assert len(items) == 1
    assert items[0].raw_metadata["sec_form"] == "20-F/A"
    assert items[0].raw_metadata["revision_semantics"] == "amendment"


def test_missing_mapping_keeps_independent_success_and_reports_partial():
    connector = SgEdgarConnector(client=Client(responses()), identities=(identity(),))
    items = connector.collect(request("Y92", "D05"))
    assert len(items) == 1
    assert connector.last_collection_status == "partial"
    assert connector.last_errors[0].ticker == "D05"


def test_all_failures_are_unavailable_not_empty():
    connector = SgEdgarConnector(client=Client({}), identities=())
    assert connector.collect(request("D05")) == []
    assert connector.last_collection_status == "unavailable"


def test_mapping_schema_rejects_extra_or_ambiguous_entries(tmp_path):
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps({"schema": IDENTITY_SCHEMA, "identities": [], "extra": True}), encoding="utf-8")
    with pytest.raises(SgEdgarDataError):
        load_identities_from_path(bad)
