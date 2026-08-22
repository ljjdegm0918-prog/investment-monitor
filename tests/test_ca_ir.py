import json
from datetime import date
from pathlib import Path

import pytest

from investment_monitor.models import CollectionRequest
from investment_monitor.sources.ca_ir import (
    CONFIG_SCHEMA,
    CaIrConnector,
    CaIrDataError,
    CaIrRequestError,
    CaIrSource,
    CaIrUrlRule,
    classify_ca_filing,
    load_sources_from_path,
)


FIXTURES = Path(__file__).parent / "fixtures" / "ca_ir"


def source(fmt: str, *, source_id: str = "issuer-feed") -> CaIrSource:
    return CaIrSource(
        source_id=source_id,
        ticker="ABC.TO",
        issuer="ABC Mining Inc.",
        exchange="TSX",
        feed_url=f"https://ir.example.ca/{fmt}",
        format=fmt,
        url_rules=(CaIrUrlRule("ir.example.ca", "/"),),
        filing_terms=(
            "financial results", "annual report", "financing",
            "technical report", "trading halt",
        ),
    )


def request():
    return CollectionRequest(
        tickers=("ABC",), start_date=date(2026, 8, 20),
        end_date=date(2026, 8, 20), markets={"ABC": "ca"},
    )


@pytest.mark.parametrize(
    "fmt,fixture,expected",
    [
        ("rss", "feed.rss", "financial_results"),
        ("atom", "feed.atom", "annual_report"),
        ("json", "feed.json", "financing"),
        ("sitemap", "sitemap.xml", "technical_report"),
        ("html", "list.html", "trading_halt"),
    ],
)
def test_ir_formats_extract_only_verified_filings(fmt, fixture, expected):
    connector = CaIrConnector(
        sources=(source(fmt),),
        fetcher=lambda _url: (FIXTURES / fixture).read_text(),
    )
    items = connector.collect(request())
    assert len(items) == 1
    assert items[0].document_type == expected
    assert items[0].source_type == "regulatory_filing"
    assert items[0].raw_metadata["source_tier"] == 2
    assert items[0].raw_metadata["issuer_exchange"] == "TSX"
    assert connector.last_collection_status == "partial"
    assert connector.last_excluded_non_filings == (1 if fmt == "rss" else 0)


def test_primary_failure_keeps_fallback_and_marks_partial():
    primary = source("rss", source_id="primary")
    fallback = source("json", source_id="fallback")

    def fetch(url):
        if url.endswith("/rss"):
            raise CaIrRequestError("HTTP 403")
        return (FIXTURES / "feed.json").read_text()

    connector = CaIrConnector(sources=(primary, fallback), fetcher=fetch)
    items = connector.collect(request())
    assert len(items) == 1
    assert connector.last_collection_status == "partial"
    assert connector.last_source_statuses == {
        "primary": "unavailable", "fallback": "partial"
    }
    assert connector.last_failure_details[0]["feed"] == "primary"


def test_standard_html_article_adapter_needs_no_private_attributes():
    standard = CaIrSource(
        source_id="standard-html", ticker="ABC", issuer="ABC Mining",
        exchange="TSX", feed_url="https://ir.example.ca/releases",
        format="html", url_rules=(CaIrUrlRule("ir.example.ca", "/"),),
        filing_terms=("dividend",),
    )
    connector = CaIrConnector(
        sources=(standard,),
        fetcher=lambda _url: (FIXTURES / "standard-list.html").read_text(),
    )
    items = connector.collect(request())
    assert len(items) == 1
    assert items[0].document_type == "dividend"


def test_transient_error_retries_but_403_does_not():
    calls = []
    sleeps = []

    def transient(_url):
        calls.append(1)
        if len(calls) == 1:
            raise CaIrRequestError("timed out")
        return (FIXTURES / "feed.rss").read_text()

    connector = CaIrConnector(
        sources=(source("rss"),), fetcher=transient,
        sleeper=sleeps.append,
    )
    assert len(connector.collect(request())) == 1
    assert len(calls) == 2
    assert sleeps == [1]

    blocked_calls = []
    blocked = CaIrConnector(
        sources=(source("rss"),),
        fetcher=lambda _url: blocked_calls.append(1) or (_ for _ in ()).throw(
            CaIrRequestError("HTTP 403")
        ),
        sleeper=sleeps.append,
    )
    assert blocked.collect(request()) == []
    assert len(blocked_calls) == 1


def test_reviewed_page_urls_are_all_collected_and_repeats_fail_closed():
    paged = CaIrSource(
        source_id="paged", ticker="ABC", issuer="ABC Mining", exchange="TSX",
        feed_url="https://ir.example.ca/page/1", format="json",
        url_rules=(CaIrUrlRule("ir.example.ca", "/"),),
        filing_terms=("financing",),
        page_urls=("https://ir.example.ca/page/2",),
    )
    payload = json.loads((FIXTURES / "feed.json").read_text())

    def fetch(url):
        row = dict(payload["items"][0])
        row["id"] = url.rsplit("/", 1)[-1]
        return json.dumps({"items": [row]})

    connector = CaIrConnector(sources=(paged,), fetcher=fetch)
    assert len(connector.collect(request())) == 2
    assert connector.last_records_read == 2
    assert connector.last_collection_status == "partial"

    repeated = CaIrConnector(
        sources=(paged,), fetcher=lambda _url: json.dumps(payload)
    )
    assert repeated.collect(request()) == []
    assert repeated.last_collection_status == "unavailable"
    assert "repeated" in repeated.last_errors[0][1]


def test_malformed_or_outside_allowlist_fails_closed():
    connector = CaIrConnector(
        sources=(source("json"),),
        fetcher=lambda _url: json.dumps({"items": [{
            "id": "x", "title": "Annual report",
            "published": "2026-08-20", "url": "https://evil.example/x",
        }]}),
    )
    assert connector.collect(request()) == []
    assert connector.last_collection_status == "unavailable"
    assert "allowlist" in connector.last_errors[0][1]


def test_strict_local_config_loader(tmp_path):
    path = tmp_path / "ca-ir.json"
    path.write_text(json.dumps({
        "schema": CONFIG_SCHEMA,
        "sources": [{
            "source_id": "abc", "ticker": "ABC", "issuer": "ABC Mining",
            "exchange": "TSX", "feed_url": "https://ir.example.ca/rss",
            "format": "rss", "url_rules": [{"host": "ir.example.ca"}],
            "filing_terms": ["annual report"],
        }],
    }))
    loaded = load_sources_from_path(path)
    assert loaded[0].ticker == "ABC"
    path.write_text(json.dumps({"schema": "wrong", "sources": []}))
    with pytest.raises(ValueError):
        load_sources_from_path(path)


def test_taxonomy_has_required_safe_fallback():
    assert classify_ca_filing("Board approves normal course issuer bid") == "share_buyback"
    assert classify_ca_filing("Unclassified regulatory document") == "other_filing"
