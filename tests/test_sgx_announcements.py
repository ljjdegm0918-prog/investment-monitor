from datetime import date
from pathlib import Path

import pytest

from investment_monitor.models import CollectionRequest
from investment_monitor.sources.sgx_announcements import (
    SgxAnnouncementConnector,
    SgxAnnouncementDataError,
    SgxAnnouncementDiscovery,
    SgxAnnouncementRequestError,
    parse_sgx_announcement_detail,
)


FIXTURE = Path(__file__).parent / "fixtures" / "sgx_announcements" / "detail_two_attachments.html"
URL = "https://links.sgx.com/1.0.0/corporate-announcements/Y93F0HCPJT1MS85Q/"


def request():
    return CollectionRequest(
        tickers=("Z74.SI",), start_date=date(2026, 6, 23),
        end_date=date(2026, 6, 23), markets={"Z74.SI": "sg"},
    )


def test_parses_known_official_detail_and_multiple_attachments():
    parsed = parse_sgx_announcement_detail(FIXTURE.read_text(), source_url=URL)
    assert parsed.issuer_name == "SINGTEL"
    assert parsed.ticker == "Z74"
    assert parsed.isin == "SG1T75931496"
    assert parsed.announcement_reference == "SG260623OTHRXBY2"
    assert parsed.broadcast_at.isoformat() == "2026-06-23T18:39:50+08:00"
    assert len(parsed.attachments) == 2
    assert parsed.attachments[0]["size"] == "4.2 MB"


def test_parses_live_label_variant_and_archive_attachment():
    html = FIXTURE.read_text().replace(
        "Date &amp; Time of Broadcast", "Date &amp;Time of Broadcast"
    ).replace(
        "23 Jun 2026 18:39:50 SGT", "23-Jun-2026 18:39:50"
    ).replace(
        "/1.0.0/corporate-announcements/Y93F0HCPJT1MS85Q/111111",
        "/FileOpen/AnnualReport.ashx?App=ArchiveAnnouncement&amp;FileID=111111",
    )
    parsed = parse_sgx_announcement_detail(html, source_url=URL)
    assert parsed.broadcast_at.isoformat() == "2026-06-23T18:39:50+08:00"
    assert parsed.attachments[0]["url"].startswith("https://links.sgx.com/FileOpen/")


def test_connector_preserves_discovery_and_official_provenance():
    discovery = SgxAnnouncementDiscovery(
        URL, "issuer_ir", "https://www.singtel.com/about-us/investor-relations", "Z74"
    )
    connector = SgxAnnouncementConnector(
        discoveries=(discovery,), fetcher=lambda _url: FIXTURE.read_text(),
        sleeper=lambda _seconds: None,
    )
    items = connector.collect(request())
    assert len(items) == 1
    item = items[0]
    assert item.source == "sgx_announcements"
    assert item.source_type == "regulatory_filing"
    assert item.document_type == "annual_report"
    assert item.raw_metadata["source_tier"] == 1
    assert item.raw_metadata["official_document"] is True
    assert item.raw_metadata["discovery_source"] == "issuer_ir"
    assert len(item.raw_metadata["attachment_urls"]) == 2
    assert connector.last_collection_status == "partial"


def test_wrong_host_loading_and_missing_fields_fail_closed():
    with pytest.raises(ValueError):
        SgxAnnouncementDiscovery(
            "https://evil.example/1.0.0/corporate-announcements/ABC/", "manual"
        )
    with pytest.raises(SgxAnnouncementDataError):
        parse_sgx_announcement_detail("<html>Loading</html>", source_url=URL)
    with pytest.raises(SgxAnnouncementDataError):
        parse_sgx_announcement_detail("<html>Announcement Title</html>", source_url=URL)


def test_403_does_not_retry_and_transient_error_does():
    discovery = SgxAnnouncementDiscovery(URL, "manual", ticker="Z74")
    blocked_calls = []

    def blocked(_url):
        blocked_calls.append(1)
        raise SgxAnnouncementRequestError("HTTP 403")

    connector = SgxAnnouncementConnector(
        discoveries=(discovery,), fetcher=blocked, sleeper=lambda _seconds: None,
    )
    assert connector.collect(request()) == []
    assert len(blocked_calls) == 1
    assert connector.last_collection_status == "unavailable"

    calls = []
    def transient(_url):
        calls.append(1)
        if len(calls) == 1:
            raise SgxAnnouncementRequestError("timeout")
        return FIXTURE.read_text()
    recovered = SgxAnnouncementConnector(
        discoveries=(discovery,), fetcher=transient, sleeper=lambda _seconds: None,
    )
    assert len(recovered.collect(request())) == 1
    assert len(calls) == 2


def test_known_list_empty_is_not_success():
    connector = SgxAnnouncementConnector(discoveries=())
    assert connector.collect(request()) == []
    assert connector.last_collection_status == "unavailable"
