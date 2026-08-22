from __future__ import annotations

from datetime import date
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import pytest

from investment_monitor.models import CollectionRequest
from investment_monitor.sources.afm_nl import (
    AFM_CONTEXT_ID,
    AfmNlClient,
    AfmNlConnector,
    AfmNlDataError,
    AfmNlRequestError,
    parse_afm_page,
)

FIXTURES = Path(__file__).parent / "fixtures" / "afm_nl"


def _fixture(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


def _page(total: int, page: int, ids: list[int], *, date_from: str = "01-08-2026", date_till: str = "21-08-2026") -> str:
    rows = "".join(
        f'''<tr class="jq_registers_register-paged-list_results_tr">
        <td><a href="/details?id=C2608-{value:05d}">20 aug 2026 - 10:00</a></td>
        <td>Issuer {value} N.V.</td><td>Results {value}</td></tr>'''
        for value in ids
    )
    return f'''<div id="registers_register-paged-list_div" data-page-size="50"
      data-context-item-id="{AFM_CONTEXT_ID}" data-date-from="{date_from}" data-date-till="{date_till}">
      <span class="cc-em--table__results"><strong>{total}</strong> Resultaten</span>
      <table data-register-view="register-overview-paged-list"><tbody>{rows}</tbody></table>
      <a class="cc-pagination__link--active" data-page-number="{page}">{page}</a></div>'''


def test_parse_real_shape_and_dutch_timestamp() -> None:
    page = parse_afm_page(_fixture("results_two.html"), "https://afm.test/page")
    assert page.total == 2
    assert page.records[0]["native_id"] == "C2608-00947"
    assert page.records[0]["published_at"].isoformat() == "2026-08-20T10:00:00+02:00"
    assert page.records[0]["url"].endswith("details?id=C2608-00947")


def test_verified_zero_is_empty() -> None:
    client = AfmNlClient(fetcher=lambda _url: _fixture("results_zero.html"), page_delay=0)
    assert tuple(client.fetch(date(2020, 1, 1), date(2020, 1, 1))) == ()


def test_client_reads_every_page_and_reconciles_total() -> None:
    requested: list[int] = []

    def fetch(url: str) -> str:
        query = parse_qs(urlparse(url).query)
        current = int(query["currentPage"][0])
        requested.append(current)
        if current == 1:
            return _page(51, 1, list(range(1, 51)))
        return _page(51, 2, [51])

    records = tuple(
        AfmNlClient(fetcher=fetch, page_delay=0).fetch(
            date(2026, 8, 1), date(2026, 8, 21)
        )
    )
    assert len(records) == 51
    assert requested == [1, 2]


@pytest.mark.parametrize(
    "second",
    [
        _page(51, 2, [50]),
        _page(52, 2, [51, 52]),
        _page(51, 1, [51]),
        _page(51, 2, [], date_from="02-08-2026"),
    ],
)
def test_client_rejects_overlap_total_page_or_filter_drift(second: str) -> None:
    calls = 0

    def fetch(_url: str) -> str:
        nonlocal calls
        calls += 1
        return _page(51, 1, list(range(1, 51))) if calls == 1 else second

    with pytest.raises(AfmNlDataError):
        tuple(AfmNlClient(fetcher=fetch, page_delay=0).fetch(date(2026, 8, 1), date(2026, 8, 21)))


def test_client_rejects_cap_and_suspicious_html() -> None:
    with pytest.raises(AfmNlDataError, match="max_pages"):
        tuple(
            AfmNlClient(fetcher=lambda _url: _page(51, 1, list(range(1, 51))), max_pages=1).fetch(
                date(2026, 8, 1), date(2026, 8, 21)
            )
        )
    for payload in ("<html>Loading...</html>", "<html>Sign in</html>", "<html></html>"):
        with pytest.raises(AfmNlDataError):
            parse_afm_page(payload, "https://afm.test")


class FakeClient:
    def __init__(self, records=(), error: Exception | None = None) -> None:
        self.records = records
        self.error = error

    def fetch(self, _start: date, _end: date):
        if self.error:
            raise self.error
        return self.records


def _record(issuer: str = "Wolters Kluwer N.V.") -> dict:
    page = parse_afm_page(_fixture("results_two.html"), "https://afm.test")
    return dict(page.records[0], issuer=issuer)


def _request() -> CollectionRequest:
    return CollectionRequest(
        tickers=("WKL.AS",),
        start_date=date(2026, 8, 20),
        end_date=date(2026, 8, 20),
        markets={"WKL.AS": "nl"},
    )


def test_connector_maps_tier_one_official_record() -> None:
    connector = AfmNlConnector(
        client=FakeClient((_record(),)),
        universe={"WKL": {"name": "Wolters Kluwer N.V.", "isin": "NL0000395903"}},
    )
    items = connector.collect(_request())
    assert len(items) == 1
    item = items[0]
    assert item.tickers == ("WKL",)
    assert item.raw_metadata["source_tier"] == 1
    assert item.raw_metadata["afm_record_id"] == "C2608-00947"
    assert item.raw_metadata["official_source_url"].endswith("id=C2608-00947")
    assert connector.last_collection_status == "success"


def test_connector_keeps_unmatched_identity_pending_and_marks_partial() -> None:
    connector = AfmNlConnector(
        client=FakeClient((_record("Unknown Holdings N.V."),)),
        universe={"WKL": {"name": "Wolters Kluwer N.V."}},
    )
    items = connector.collect(_request())
    assert len(items) == 1
    assert items[0].tickers == ()
    assert items[0].raw_metadata["match_status"] == "pending_matching"
    assert connector.last_collection_status == "partial"
    assert connector.last_unmatched_records == 1
    assert connector.last_pending_records[0]["match_status"] == "pending_matching"


def test_connector_failure_is_unavailable_not_empty() -> None:
    connector = AfmNlConnector(
        client=FakeClient(error=RuntimeError("HTTP 403")),
        universe={"WKL": {"name": "Wolters Kluwer N.V."}},
    )
    with pytest.raises(AfmNlRequestError):
        connector.collect(_request())
    assert connector.last_collection_status == "unavailable"
    assert "403" in connector.last_errors[0][1]
