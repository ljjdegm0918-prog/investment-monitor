from datetime import date
import json
from pathlib import Path
from unittest.mock import patch

from investment_monitor.models import CollectionRequest
from investment_monitor.sources.cse_filings import (
    CseFilingRequestError,
    CseFilingsConnector,
    CseIssuerIdentity,
)


FIXTURES = Path(__file__).parent / "fixtures" / "cse_filings"
SECURITY_URL = (
    "https://webapi-backup.thecse.com/trading/listed/securities/CARM.json"
)
FILINGS_URL = (
    "https://webapi-backup.thecse.com/trading/listed/"
    "sedar_filings/000053969.json"
)


def _payload(name: str):
    return json.loads((FIXTURES / name).read_text())


def _request(*tickers: str) -> CollectionRequest:
    return CollectionRequest(
        tickers=tickers or ("CARM",),
        start_date=date(2026, 4, 14),
        end_date=date(2026, 4, 14),
        markets={ticker: "ca" for ticker in tickers or ("CARM",)},
    )


def test_official_cse_identity_chain_maps_window_and_removed_revision():
    calls = []

    def fetch(url):
        calls.append(url)
        return _payload("security.json" if url == SECURITY_URL else "filings.json")

    connector = CseFilingsConnector(
        identities=(CseIssuerIdentity("CARM.CN", "Carmanah Minerals Corp."),),
        fetcher=fetch,
        sleeper=lambda _seconds: None,
    )
    items = connector.collect(_request("CARM"))
    assert calls == [SECURITY_URL, FILINGS_URL]
    assert len(items) == 2
    assert items[0].document_type == "interim_report"
    assert items[0].raw_metadata["source_tier"] == 1
    assert items[0].raw_metadata["mirror"] is True
    assert items[0].raw_metadata["not_sedar_plus_primary"] is True
    assert items[0].raw_metadata["attachment_urls"] == [items[0].url]
    assert items[1].raw_metadata["revision_semantics"] == "withdrawal"
    assert connector.last_records_read == 3
    assert connector.last_collection_status == "success"


def test_identity_mismatch_and_count_mismatch_fail_closed():
    wrong = _payload("security.json")
    wrong["metadata"]["symbol"] = "OTHER"
    connector = CseFilingsConnector(
        identities=(CseIssuerIdentity("CARM", "Carmanah Minerals Corp."),),
        fetcher=lambda _url: wrong,
    )
    assert connector.collect(_request("CARM")) == []
    assert connector.last_collection_status == "unavailable"

    bad_count = _payload("filings.json")
    bad_count["categories"]["NEWS_RELEASES"] = 2
    connector = CseFilingsConnector(
        identities=(CseIssuerIdentity("CARM", "Carmanah Minerals Corp."),),
        fetcher=lambda url: _payload("security.json") if url == SECURITY_URL else bad_count,
    )
    assert connector.collect(_request("CARM")) == []
    assert "count" in connector.last_errors[0][1]


def test_403_is_not_retried_and_other_issuer_success_is_preserved():
    calls = []

    def fetch(url):
        calls.append(url)
        if "FAIL" in url:
            raise CseFilingRequestError("HTTP 403")
        return _payload("security.json" if "securities" in url else "filings.json")

    connector = CseFilingsConnector(
        identities=(
            CseIssuerIdentity("FAIL", "Failure Corp."),
            CseIssuerIdentity("CARM", "Carmanah Minerals Corp."),
        ),
        fetcher=fetch,
        sleeper=lambda _seconds: None,
        retry_attempts=4,
    )
    assert len(connector.collect(_request("FAIL", "CARM"))) == 2
    assert sum("FAIL" in url for url in calls) == 1
    assert connector.last_collection_status == "partial"


def test_non_cse_ticker_is_not_probed():
    connector = CseFilingsConnector(
        identities=(CseIssuerIdentity("CARM", "Carmanah Minerals Corp."),),
        fetcher=lambda _url: (_ for _ in ()).throw(AssertionError("network")),
    )
    assert connector.collect(_request("RY")) == []
    assert connector.last_collection_status == "empty"


def test_environment_factory_refreshes_cold_universe_before_loading_identities():
    identity = CseIssuerIdentity("CARM.CN", "Carmanah Minerals Corp.")
    with (
        patch(
            "investment_monitor.sources.cse_filings.connector._load_identities",
            side_effect=((), (), (identity,)),
        ) as load,
        patch(
            "investment_monitor.sources.cse_filings.connector.refresh_ca_universe"
        ) as refresh,
    ):
        connector = CseFilingsConnector.from_environment()

    assert connector._identities == {"CARM": identity}
    assert load.call_count == 3
    refresh.assert_called_once_with()
