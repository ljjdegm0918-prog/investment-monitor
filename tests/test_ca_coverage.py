from datetime import datetime, timezone

from investment_monitor.ca_coverage import calculate_ca_coverage


def test_ca_coverage_measures_exchanges_and_never_claims_complete():
    universe = {
        "items": [
            {"ticker": "RY", "exchange": "TSX", "investor_relations_url": "https://rbc.example/ir", "ir_feed_url": "https://rbc.example/feed"},
            {"ticker": "ABC", "exchange": "TSXV"},
            {"ticker": "XYZ", "exchange": "CSE"},
            {"ticker": "OLD", "exchange": "CSE", "status": "delisted"},
        ]
    }
    items = [{
        "market": "ca", "source": "ca_ir", "ticker": "RY",
        "published_at": "2026-08-20T12:00:00-04:00", "dedupe_count": 2,
        "raw_metadata": {"attachments": [{"url": "https://rbc.example/a.pdf"}]},
    }]
    result = calculate_ca_coverage(
        universe, items,
        source_statuses=({"status": "partial"},),
        now=datetime(2026, 8, 22, tzinfo=timezone.utc),
    )
    assert result["listed_companies_total"] == 3
    assert result["historical_delisted_listings"] == 1
    assert set(result["exchange_coverage"]) == {"TSX", "TSXV", "CSE"}
    assert result["cross_verified_items"] == 1
    assert result["incomplete_source_count"] == 1
    assert result["rating"] == "partial"
    assert result["maximum_rating"] == "high"


def test_ca_coverage_counts_cse_filing_as_a_real_source_not_an_ir_feed():
    universe = {"items": [{"ticker": "XYZ", "exchange": "CSE"}]}
    result = calculate_ca_coverage(
        universe,
        [{
            "market": "ca",
            "source": "cse_filings",
            "ticker": "XYZ",
            "published_at": "2026-08-20T12:00:00-04:00",
            "raw_metadata": {
                "attachment_urls": ["https://cse.example/a.pdf"]
            },
        }],
        now=datetime(2026, 8, 22, tzinfo=timezone.utc),
    )
    assert result["usable_announcement_feeds"] == 0
    assert result["issuers_with_any_source"] == 1
    assert result["exchange_coverage"]["CSE"]["with_source"] == 1
    assert result["exchange_coverage"]["CSE"]["source_ratio"] == 1.0


def test_ca_coverage_is_unavailable_without_universe():
    result = calculate_ca_coverage(None, ())
    assert result["rating"] == "unavailable"
