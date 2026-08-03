"""Generate a static HTML report from standardized repository records."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from html import escape
from pathlib import Path
from typing import Iterable, List, Mapping, Sequence, Tuple

from .config import UniverseEntry
from .models import InformationItem
from .pipeline import CollectionFailure
from .repository import InformationRepository

LIST_TYPE_ORDER = ("holdings", "planned", "watchlist")
LIST_TYPE_LABELS = {
    "holdings": "Holdings",
    "planned": "Planned",
    "watchlist": "Watchlist",
}


@dataclass(frozen=True)
class ReportResult:
    output_path: Path
    record_count: int
    ticker_count: int
    failure_count: int


def generate_html_report(
    *,
    repository: InformationRepository,
    universe: Sequence[UniverseEntry],
    enabled_sources: Sequence[str],
    start_date: date,
    end_date: date,
    failures: Iterable[CollectionFailure],
    output_path: Path,
) -> ReportResult:
    """Query standardized records and write a standalone HTML report."""
    if start_date > end_date:
        raise ValueError("start_date must not be after end_date.")

    failure_list = tuple(failures)
    records_by_ticker = _query_records_by_ticker(
        repository=repository,
        universe=universe,
        enabled_sources=enabled_sources,
        start_date=start_date,
        end_date=end_date,
    )
    record_count = sum(len(items) for items in records_by_ticker.values())
    body_sections = [
        _render_failures(failure_list),
        _render_universe_groups(universe, records_by_ticker),
    ]
    document = _render_document(
        start_date=start_date,
        end_date=end_date,
        body="\n".join(body_sections),
    )

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(document, encoding="utf-8")
    return ReportResult(
        output_path=output_path,
        record_count=record_count,
        ticker_count=len(universe),
        failure_count=len(failure_list),
    )


def _query_records_by_ticker(
    *,
    repository: InformationRepository,
    universe: Sequence[UniverseEntry],
    enabled_sources: Sequence[str],
    start_date: date,
    end_date: date,
) -> Mapping[str, Tuple[InformationItem, ...]]:
    records_by_ticker = {}
    for entry in universe:
        records: List[InformationItem] = []
        for source in enabled_sources:
            records.extend(
                repository.query(
                    ticker=entry.ticker,
                    source=source,
                    start_date=start_date,
                    end_date=end_date,
                )
            )
        records.sort(
            key=lambda item: (
                item.published_at,
                item.source,
                item.external_id,
            ),
            reverse=True,
        )
        records_by_ticker[entry.ticker] = tuple(records)
    return records_by_ticker


def _render_document(*, start_date: date, end_date: date, body: str) -> str:
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Investment Announcements</title>
  <style>
    :root {{ color-scheme: light; font-family: Arial, sans-serif; }}
    body {{ margin: 0; background: #f4f6f8; color: #1f2933; }}
    main {{ max-width: 1200px; margin: 0 auto; padding: 32px 20px 64px; }}
    h1, h2, h3 {{ color: #102a43; }}
    .period, .empty, .failures, .ticker-block {{
      background: white; border: 1px solid #d9e2ec; border-radius: 8px;
      padding: 16px; margin-bottom: 16px;
    }}
    .failures {{ border-left: 5px solid #c62828; }}
    .no-failures {{ border-left: 5px solid #2e7d32; }}
    .provenance-note {{ background: #fff8e1; border-left: 5px solid #f9a825;
      padding: 12px 16px; margin-bottom: 16px; }}
    .badge {{ display: inline-block; border-radius: 999px; padding: 3px 8px;
      font-size: 0.85rem; font-weight: bold; white-space: nowrap; }}
    .badge-live {{ background: #e8f5e9; color: #1b5e20; }}
    .badge-demo {{ background: #fff3e0; color: #a63c00; }}
    .group {{ margin-top: 32px; }}
    .table-wrap {{ overflow-x: auto; }}
    table {{ width: 100%; border-collapse: collapse; background: white; }}
    th, td {{ padding: 10px; border-bottom: 1px solid #d9e2ec; text-align: left; }}
    th {{ background: #eaf1f8; white-space: nowrap; }}
    a {{ color: #0b65c2; }}
    .muted {{ color: #627d98; }}
  </style>
</head>
<body>
<main>
  <h1>Investment Announcements</h1>
  <p class="period"><strong>Report period:</strong>
    <time datetime="{start_date.isoformat()}">{start_date.isoformat()}</time>
    through
    <time datetime="{end_date.isoformat()}">{end_date.isoformat()}</time>
  </p>
  <p class="provenance-note"><strong>How to read sources:</strong>
    <code>source</code> identifies the exact connector,
    <code>source type</code> identifies the content category, and
    <code>data status</code> distinguishes live records from generated demo data.
  </p>
  {body}
</main>
</body>
</html>
"""


def _render_failures(failures: Sequence[CollectionFailure]) -> str:
    if not failures:
        return (
            '<section class="failures no-failures">'
            "<h2>Collection failures</h2>"
            "<p>None. All configured source/ticker requests completed.</p>"
            "</section>"
        )

    rows = "\n".join(
        "<tr>"
        f"<td>{escape(failure.source)}</td>"
        f"<td>{escape(failure.ticker)}</td>"
        f"<td>{escape(failure.message)}</td>"
        "</tr>"
        for failure in failures
    )
    return f"""<section class="failures">
  <h2>Collection failures</h2>
  <p>The report was still generated from records available in the repository.</p>
  <div class="table-wrap">
    <table>
      <thead><tr><th>Source</th><th>Ticker</th><th>Error</th></tr></thead>
      <tbody>{rows}</tbody>
    </table>
  </div>
</section>"""


def _render_universe_groups(
    universe: Sequence[UniverseEntry],
    records_by_ticker: Mapping[str, Tuple[InformationItem, ...]],
) -> str:
    sections = []
    for list_type in LIST_TYPE_ORDER:
        entries = [entry for entry in universe if entry.list_type == list_type]
        ticker_blocks = (
            "\n".join(
                _render_ticker(
                    entry=entry,
                    records=records_by_ticker[entry.ticker],
                )
                for entry in entries
            )
            if entries
            else '<p class="empty">No tickers configured for this list.</p>'
        )
        sections.append(
            f'<section class="group" id="{list_type}">'
            f"<h2>{LIST_TYPE_LABELS[list_type]}</h2>"
            f"{ticker_blocks}"
            "</section>"
        )
    return "\n".join(sections)


def _render_ticker(
    *,
    entry: UniverseEntry,
    records: Sequence[InformationItem],
) -> str:
    if not records:
        return (
            '<article class="ticker-block">'
            f"<h3>{escape(entry.ticker)}</h3>"
            f'<p class="empty">No records found for {escape(entry.ticker)} '
            "in the report period.</p>"
            "</article>"
        )

    rows = "\n".join(
        _render_record_row(entry=entry, item=item)
        for item in records
    )
    return f"""<article class="ticker-block">
  <h3>{escape(entry.ticker)}</h3>
  <div class="table-wrap">
    <table>
      <thead>
        <tr>
          <th>Source</th>
          <th>Source type</th>
          <th>Data status</th>
          <th>List type</th>
          <th>Ticker</th>
          <th>Issuer</th>
          <th>Publication date</th>
          <th>Document type</th>
          <th>Title</th>
          <th>Original</th>
        </tr>
      </thead>
      <tbody>{rows}</tbody>
    </table>
  </div>
</article>"""


def _render_record_row(
    *,
    entry: UniverseEntry,
    item: InformationItem,
) -> str:
    url = escape(item.url, quote=True)
    is_demo = item.raw_metadata.get("generated") is True
    data_status = (
        '<span class="badge badge-demo">Demo / generated</span>'
        if is_demo
        else '<span class="badge badge-live">Live</span>'
    )
    original_link = (
        '<span class="muted">Demo URL — not live</span>'
        if is_demo
        else (
            f'<a href="{url}" target="_blank" rel="noopener noreferrer">'
            "Open original</a>"
        )
    )
    return (
        "<tr>"
        f"<td>{escape(item.source)}</td>"
        f"<td>{escape(item.source_type)}</td>"
        f"<td>{data_status}</td>"
        f"<td>{escape(entry.list_type)}</td>"
        f"<td>{escape(entry.ticker)}</td>"
        f"<td>{escape(item.issuer)}</td>"
        f'<td><time datetime="{item.published_at.isoformat()}">'
        f"{item.published_at.date().isoformat()}</time></td>"
        f"<td>{escape(item.document_type)}</td>"
        f"<td>{escape(item.title)}</td>"
        f"<td>{original_link}</td>"
        "</tr>"
    )
