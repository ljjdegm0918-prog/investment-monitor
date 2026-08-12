from datetime import date, datetime, timedelta, timezone
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import gc
import unittest
import sqlite3

from investment_monitor import (
    InformationItem,
    InformationRepository,
    SQLiteInformationRepository,
)
from provenance_assertions import canonical_payload_hash


def make_item(
    *,
    source: str,
    external_id: str,
    ticker: str,
    published_at: datetime,
    source_type: str = "regulatory_filing",
    raw_metadata=None,
) -> InformationItem:
    return InformationItem(
        source=source,
        source_type=source_type,
        external_id=external_id,
        tickers=(ticker,),
        issuer=f"{ticker} Issuer",
        published_at=published_at,
        title=f"Item {external_id}",
        document_type="10-Q",
        url=f"https://example.test/{external_id}",
        collected_at=datetime(2026, 7, 27, tzinfo=timezone.utc),
        raw_metadata=raw_metadata or {"fixture": True},
    )


class SQLiteInformationRepositoryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = TemporaryDirectory()
        database_path = (
            Path(self.temporary_directory.name) / "information.sqlite3"
        )
        self.repository = SQLiteInformationRepository(database_path)

    def tearDown(self) -> None:
        self.repository = None  # type: ignore[assignment]
        gc.collect()
        self.temporary_directory.cleanup()

    def test_implements_repository_interface_and_queries_all_filters(self) -> None:
        self.assertIsInstance(self.repository, InformationRepository)
        apple_item = make_item(
            source="sec",
            external_id="sec-1",
            ticker="AAPL",
            published_at=datetime(2026, 1, 10, tzinfo=timezone.utc),
        )
        microsoft_item = make_item(
            source="mock",
            source_type="mock",
            external_id="mock-1",
            ticker="MSFT",
            published_at=datetime(2026, 2, 10, tzinfo=timezone.utc),
        )

        result = self.repository.save([apple_item, microsoft_item])

        self.assertEqual(result.inserted, 2)
        self.assertEqual(result.updated, 0)
        self.assertEqual(
            self.repository.query(ticker="aapl"),
            [apple_item],
        )
        self.assertEqual(
            self.repository.query(source="sec"),
            [apple_item],
        )
        self.assertEqual(
            self.repository.query(source_type="mock"),
            [microsoft_item],
        )
        self.assertEqual(
            self.repository.query(
                start_date=date(2026, 2, 1),
                end_date=date(2026, 2, 28),
            ),
            [microsoft_item],
        )

    def test_source_and_external_id_deduplicate_repeated_saves(self) -> None:
        sec_item = make_item(
            source="sec",
            external_id="shared-id",
            ticker="AAPL",
            published_at=datetime(2026, 1, 10, tzinfo=timezone.utc),
        )
        same_identity_updated = InformationItem(
            source=sec_item.source,
            source_type=sec_item.source_type,
            external_id=sec_item.external_id,
            tickers=sec_item.tickers,
            issuer=sec_item.issuer,
            published_at=sec_item.published_at,
            title="Updated title",
            document_type=sec_item.document_type,
            url=sec_item.url,
            collected_at=sec_item.collected_at,
            raw_metadata=sec_item.raw_metadata,
        )
        other_source_item = make_item(
            source="mock",
            external_id="shared-id",
            ticker="AAPL",
            published_at=datetime(2026, 1, 10, tzinfo=timezone.utc),
            source_type="mock",
        )

        first = self.repository.save([sec_item])
        second = self.repository.save([same_identity_updated])
        third = self.repository.save([other_source_item])

        self.assertEqual(first.inserted, 1)
        self.assertEqual(second.updated, 1)
        self.assertEqual(third.inserted, 1)
        self.assertEqual(self.repository.count(), 2)
        stored_sec_item = self.repository.query(source="sec")[0]
        self.assertEqual(stored_sec_item.title, "Updated title")

    def test_tdnet_logical_item_keeps_distinct_immutable_versions(self) -> None:
        first = make_item(
            source="tdnet_public_web",
            external_id="synthetic:stable",
            ticker="7203",
            published_at=datetime(2026, 8, 7, 1, tzinfo=timezone.utc),
        )
        first = InformationItem(
            **{
                **first.__dict__,
                "market": "jp",
                "raw_metadata": {
                    "raw_content_hash": "hash-one",
                    "official_source_url": "https://example.test/page",
                },
            }
        )
        second = InformationItem(
            **{
                **first.__dict__,
                "title": "Changed observation",
                "raw_metadata": {
                    "raw_content_hash": "hash-two",
                    "official_source_url": "https://example.test/page",
                },
            }
        )
        self.repository.save([first])
        self.repository.save([second])
        with sqlite3.connect(str(self.repository._database_path)) as connection:
            count = connection.execute(
                "SELECT COUNT(*) FROM information_item_versions"
            ).fetchone()[0]
        self.assertEqual(self.repository.count(), 1)
        self.assertEqual(count, 2)

    def test_v1_regulatory_filing_versions_raw_changes_idempotently(self) -> None:
        first_payload = {"id": "official-1", "status": "published"}
        first_url = "https://official.example/filings/official-1"
        first = make_item(
            source="official_fixture",
            external_id="official-1",
            ticker="FIX",
            published_at=datetime(2026, 8, 7, tzinfo=timezone.utc),
            raw_metadata={
                "provenance_schema_version": 1,
                "official_source_url": first_url,
                "raw_payload": first_payload,
                "raw_content_hash": canonical_payload_hash(first_payload),
                "revision_semantics": "unknown",
            },
        )
        changed_payload = {"id": "official-1", "status": "corrected"}
        refetched = InformationItem(
            **{
                **first.__dict__,
                "title": "Same raw filing observed again",
                "collected_at": datetime(2026, 8, 8, tzinfo=timezone.utc),
            }
        )
        changed = InformationItem(
            **{
                **first.__dict__,
                "title": "Corrected filing",
                "raw_metadata": {
                    **first.raw_metadata,
                    "raw_payload": changed_payload,
                    "raw_content_hash": canonical_payload_hash(changed_payload),
                },
            }
        )

        self.repository.save([first])
        self.repository.save([refetched])
        self.repository.save([changed])

        with sqlite3.connect(str(self.repository._database_path)) as connection:
            rows = connection.execute(
                "SELECT snapshot_hash, payload, provenance_url, revision_status "
                "FROM information_item_versions ORDER BY id"
            ).fetchall()
        self.assertEqual(len(rows), 2)
        self.assertEqual(
            [row[0] for row in rows],
            [
                canonical_payload_hash(first_payload),
                canonical_payload_hash(changed_payload),
            ],
        )
        self.assertEqual(
            [json.loads(row[1])["raw_metadata"]["raw_payload"] for row in rows],
            [first_payload, changed_payload],
        )
        self.assertEqual([row[2] for row in rows], [first_url, first_url])
        self.assertEqual([row[3] for row in rows], ["unknown", "unknown"])
        self.assertEqual(self.repository.count(), 1)

    def test_legacy_regulatory_filing_without_schema_remains_compatible(self) -> None:
        legacy = make_item(
            source="legacy_official_fixture",
            external_id="legacy-1",
            ticker="FIX",
            published_at=datetime(2026, 8, 7, tzinfo=timezone.utc),
            raw_metadata={"fixture": True, "official_source_url": None},
        )

        result = self.repository.save([legacy])

        self.assertEqual(result.inserted, 1)
        self.assertEqual(self.repository.query(source=legacy.source), [legacy])
        with sqlite3.connect(str(self.repository._database_path)) as connection:
            count = connection.execute(
                "SELECT COUNT(*) FROM information_item_versions"
            ).fetchone()[0]
        self.assertEqual(count, 0)

    def test_exact_utc_range_is_half_open_at_24_hour_boundaries(self) -> None:
        start = datetime(2026, 8, 6, 12, tzinfo=timezone.utc)
        end = datetime(2026, 8, 7, 12, tzinfo=timezone.utc)
        self.repository.save([
            make_item(source="sec", external_id="before", ticker="AAPL", published_at=start),
            make_item(source="sec", external_id="inside", ticker="AAPL", published_at=end - timedelta(minutes=1)),
            make_item(source="sec", external_id="end", ticker="AAPL", published_at=end),
        ])
        result = self.repository.query_published_between(start, end, ticker="AAPL")
        self.assertEqual([item.external_id for item in result], ["before", "inside"])


if __name__ == "__main__":
    unittest.main()
