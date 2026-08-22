from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import pytest

from investment_monitor.models import CollectionRequest
from investment_monitor.sources.wiener_boerse_news import (
    WienerBoerseClient,
    WienerBoerseDataError,
    WienerBoerseNewsConnector,
    WienerBoerseRequestError,
    parse_wiener_news_page,
)
from investment_monitor.universe.at_universe import (
    AtUniverseError,
    OVERLAY_SCHEMA,
    at_universe_name_map,
    parse_at_company_page,
    refresh_at_universe,
)

FIXTURES = Path(__file__).parent / "fixtures" / "at_official"


def _fixture(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


def test_official_company_table_filters_foreign_global_and_funds() -> None:
    items = parse_at_company_page(_fixture("companies.html"), minimum_items=3)
    assert [item["isin"] for item in items] == [
        "AT0000937503",
        "AT0000834007",
        "AT0000616701",
    ]
    assert items[2]["market"] == "Vienna MTF"
    assert items[0]["ticker"] == "AT0000937503"


def test_universe_refresh_is_atomic_and_applies_reviewed_overlay(tmp_path: Path) -> None:
    cache = tmp_path / "at.json"
    overlay = tmp_path / "overlay.json"
    overlay.write_text(
        json.dumps(
            {
                "schema": OVERLAY_SCHEMA,
                "mappings": [
                    {"isin": "AT0000937503", "ticker": "VOE", "aliases": ["VOEST"]}
                ],
            }
        ),
        encoding="utf-8",
    )
    payload = refresh_at_universe(
        path=cache,
        overlay_path=overlay,
        fetcher=lambda _url: _fixture("companies.html"),
        refreshed_at="2026-08-23T00:00:00+00:00",
        minimum_items=3,
    )
    assert payload["counts"]["issuers"] == 3
    assert payload["counts"]["reviewed_tickers"] == 1
    mapping = at_universe_name_map(cache)
    assert mapping["VOE"]["isin"] == "AT0000937503"
    assert mapping["VOEST"]["name"] == "voestalpine AG"
    assert not cache.with_suffix(".json.tmp").exists()


def test_universe_rejects_schema_drift_duplicate_and_small_payload() -> None:
    with pytest.raises(AtUniverseError, match="columns changed"):
        parse_at_company_page(_fixture("companies.html").replace("<th>Issuer</th>", "<th>Name</th>"), minimum_items=3)
    duplicate = _fixture("companies.html").replace(
        "AT0000834007", "AT0000937503"
    )
    with pytest.raises(AtUniverseError):
        parse_at_company_page(duplicate, minimum_items=3)
    with pytest.raises(AtUniverseError, match="suspiciously small"):
        parse_at_company_page(_fixture("companies.html"), minimum_items=4)


def test_universe_rejects_overlay_alias_collisions(tmp_path: Path) -> None:
    overlay = tmp_path / "overlay.json"
    overlay.write_text(
        json.dumps(
            {
                "schema": OVERLAY_SCHEMA,
                "mappings": [
                    {"isin": "AT0000937503", "ticker": "VOE", "aliases": ["WOL"]},
                    {"isin": "AT0000834007", "ticker": "WOL", "aliases": []},
                ],
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(AtUniverseError, match="duplicate ticker or alias"):
        refresh_at_universe(
            path=tmp_path / "cache.json",
            overlay_path=overlay,
            fetcher=lambda _url: _fixture("companies.html"),
            minimum_items=3,
        )


def test_news_parser_uses_opaque_id_and_excludes_non_filings() -> None:
    page = parse_wiener_news_page(_fixture("news.html"), "https://wiener.test/page")
    assert page.total == 3
    assert len(page.records) == 1
    assert page.excluded_non_filings == 2
    record = page.records[0]
    assert record["external_id"] == "wiener-boerse:3iFrDvdSnimDjQeoZnrUNg"
    assert record["issuer"] == "Wolford AG"
    assert record["published_at"].isoformat() == "2026-08-19T16:51:00+02:00"
    assert "c93603%5Bfile%5D=3iFrDvdSnimDjQeoZnrUNg" in record["url"]


def _row(index: int, raw_date: str, *, title: str | None = None) -> str:
    title = title or f"EQS-Adhoc: Issuer {index} AG: Results {index}"
    return f'''<div data-key="{index}"><div class="news-row">
      <div class="datetime">Ad-hoc News <span>&nbsp;·&nbsp;</span> {raw_date}</div>
      <div class="header-shorten"><a href="/en/news-1/?c93603%5Bfile%5D=opaqueFile{index:03d}">{title}</a></div>
    </div></div>'''


def _news_page(total: int, page: int, rows: list[str]) -> str:
    return f'''<div data-sxp-ajax-snippet="c93603-adhoc-news">
      <div>Your search resulted in <b>{total}</b> hits.</div>
      <li class="active"><a data-page="{page - 1}">{page}</a></li>
      {''.join(rows)}</div>'''


def test_client_reads_second_page_and_stops_after_covering_start_day() -> None:
    requested: list[int] = []

    def fetch(url: str) -> str:
        page = int(parse_qs(urlparse(url).query)["c93603-page"][0])
        requested.append(page)
        if page == 1:
            return _news_page(26, 1, [_row(i, "08/20/2026, 12:00:00") for i in range(25)])
        return _news_page(26, 2, [_row(25, "08/18/2026, 12:00:00")])

    records = tuple(
        WienerBoerseClient(fetcher=fetch, page_delay=0).fetch(
            date(2026, 8, 19), date(2026, 8, 20)
        )
    )
    assert len(records) == 25
    assert requested == [1, 2]


def test_client_rejects_overlap_order_cap_and_old_archive_boundary() -> None:
    first = _news_page(26, 1, [_row(i, "08/20/2026, 12:00:00") for i in range(25)])
    overlap = _news_page(26, 2, [_row(24, "08/18/2026, 12:00:00")])
    calls = 0

    def fetch_overlap(_url: str) -> str:
        nonlocal calls
        calls += 1
        return first if calls == 1 else overlap

    with pytest.raises(WienerBoerseDataError, match="overlapped"):
        tuple(WienerBoerseClient(fetcher=fetch_overlap, page_delay=0).fetch(date(2026, 8, 19), date(2026, 8, 20)))
    with pytest.raises(WienerBoerseDataError, match="max_pages"):
        tuple(WienerBoerseClient(fetcher=lambda _url: first, max_pages=1).fetch(date(2026, 8, 19), date(2026, 8, 20)))
    last_too_new = _news_page(1, 1, [_row(1, "08/20/2026, 12:00:00")])
    with pytest.raises(WienerBoerseDataError, match="does not reach"):
        tuple(WienerBoerseClient(fetcher=lambda _url: last_too_new).fetch(date(2026, 8, 1), date(2026, 8, 20)))


class FakeClient:
    last_excluded_non_filings = 0

    def __init__(self, records=(), error: Exception | None = None) -> None:
        self.records = records
        self.error = error

    def fetch(self, _start: date, _end: date):
        if self.error:
            raise self.error
        return self.records


def _official_record(issuer: str = "Wolford AG") -> dict:
    record = parse_wiener_news_page(_fixture("news.html"), "https://wiener.test").records[0]
    return dict(record, issuer=issuer)


def _request() -> CollectionRequest:
    return CollectionRequest(
        tickers=("WOL",),
        start_date=date(2026, 8, 19),
        end_date=date(2026, 8, 19),
        markets={"WOL": "at"},
    )


def test_connector_maps_official_filing_and_preserves_attachment() -> None:
    connector = WienerBoerseNewsConnector(
        client=FakeClient((_official_record(),)),
        universe={"WOL": {"name": "Wolford AG", "isin": "AT0000834007"}},
    )
    items = connector.collect(_request())
    assert len(items) == 1
    assert items[0].raw_metadata["source_tier"] == 1
    assert items[0].raw_metadata["wiener_file_id"] == "3iFrDvdSnimDjQeoZnrUNg"
    assert items[0].raw_metadata["attachment_urls"] == [items[0].url]
    assert connector.last_collection_status == "success"


def test_connector_pending_identity_is_partial_and_failure_unavailable() -> None:
    connector = WienerBoerseNewsConnector(
        client=FakeClient((dict(_official_record("Unknown AG"), title="EQS-Adhoc: Unknown AG: Results"),)),
        universe={"WOL": {"name": "Wolford AG"}},
    )
    items = connector.collect(_request())
    assert len(items) == 1
    assert items[0].tickers == ()
    assert items[0].raw_metadata["match_status"] == "pending_matching"
    assert connector.last_collection_status == "partial"
    assert connector.last_pending_records[0]["match_status"] == "pending_matching"

    connector = WienerBoerseNewsConnector(
        client=FakeClient(error=RuntimeError("HTTP 429")),
        universe={"WOL": {"name": "Wolford AG"}},
    )
    with pytest.raises(WienerBoerseRequestError):
        connector.collect(_request())
    assert connector.last_collection_status == "unavailable"
