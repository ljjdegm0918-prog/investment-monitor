"""Collect one year of AAPL filing metadata from SEC EDGAR."""

from datetime import date, timedelta

from investment_monitor import (
    CollectionPipeline,
    CollectionRequest,
    SECConnector,
    create_default_registry,
)


def main() -> None:
    end_date = date.today()
    start_date = end_date - timedelta(days=365)
    registry = create_default_registry()
    connector = registry.load_enabled(["sec"])[0]
    items = CollectionPipeline([connector]).collect(
        CollectionRequest(
            tickers=("AAPL",),
            start_date=start_date,
            end_date=end_date,
        )
    )

    print(f"AAPL filings from {start_date} through {end_date}: {len(items)}")
    for item in items[:10]:
        print(
            f"{item.published_at.date()} | {item.document_type} | "
            f"{item.title} | {item.url}"
        )

    if isinstance(connector, SECConnector) and connector.last_errors:
        for failure in connector.last_errors:
            print(f"ERROR {failure.ticker}: {failure.message}")


if __name__ == "__main__":
    main()
