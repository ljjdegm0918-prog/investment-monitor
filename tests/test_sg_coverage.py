from datetime import datetime, timezone

from investment_monitor.sg_coverage import calculate_sg_coverage


def test_sg_coverage_counts_boards_and_never_claims_complete():
    universe = {"items": [
        {"ticker": "D05", "board": "SGX Mainboard", "investor_relations_url": "https://dbs.example/ir", "ir_feed_url": "https://dbs.example/feed"},
        {"ticker": "CAT", "board": "Catalist"},
    ]}
    items = [{
        "market": "sg", "source": "sgx_announcements", "ticker": "D05",
        "published_at": "2026-08-20T18:00:00+08:00", "dedupe_count": 2,
        "raw_metadata": {"source_tier": 1, "official_document": True,
                         "attachments": [{"url": "https://links.sgx.com/a"}]},
    }]
    result = calculate_sg_coverage(
        universe, items, source_statuses=({"status": "partial"},),
        now=datetime(2026, 8, 22, tzinfo=timezone.utc),
    )
    assert result["rating"] == "partial"
    assert result["maximum_rating"] == "high"
    assert result["known_issuers"] == 2
    assert result["mainboard_issuers"] == 1
    assert result["catalist_issuers"] == 1
    assert result["official_sgx_link_announcements"] == 1
    assert result["cross_verified_ratio"] == 1.0


def test_sg_coverage_requires_actual_items():
    result = calculate_sg_coverage({"items": [{"ticker": "D05", "board": "Mainboard"}]}, ())
    assert result["rating"] == "unavailable"
    assert result["issuers_without_announcement_source"] == 1


def test_sg_coverage_counts_audited_builtin_ir_source_from_collected_items():
    result = calculate_sg_coverage(
        {"items": [{"ticker": "Z74", "board": "Mainboard"}]},
        [{
            "market": "sg",
            "source": "sg_ir",
            "ticker": "Z74",
            "published_at": "2026-08-19T12:00:00+08:00",
            "raw_metadata": {
                "source_tier": 2,
                "official_document": True,
                "attachment_urls": ["https://issuer.example/a.pdf"],
            },
        }],
        now=datetime(2026, 8, 22, tzinfo=timezone.utc),
    )
    assert result["ir_sites_found"] == 1
    assert result["usable_ir_feeds"] == 1
    assert result["board_coverage"]["Mainboard"]["with_source"] == 1
