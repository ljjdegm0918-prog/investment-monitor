"""SQLite persistence for research cards and their evidence snapshots.

Cards are stored only after server-side validation. The evidence snapshot is
written alongside each card so every evidence reference (E1, E2, ...) can be
traced back to the exact information item used at generation time. No API key
or other secret is ever written here.
"""

from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3
from typing import Any, Dict, Iterator, List, Mapping, Optional, Sequence, Tuple

from .research import (
    RESEARCH_EVIDENCE_RULE_VERSION,
    RESEARCH_PROMPT_VERSION,
    RESEARCH_SCHEMA_VERSION,
    ResearchEvidence,
    ResearchScope,
    information_type_of,
)

CARD_STATUS_GENERATING = "generating"
CARD_STATUS_COMPLETED = "completed"
CARD_STATUS_FAILED = "failed"


def _scope_filter(
    scope: Optional["ResearchScope"],
) -> Tuple[str, Tuple[Any, ...]]:
    """Return a WHERE fragment pinning a card to one exact generation scope.

    ``IS`` is NULL-safe equality in SQLite, so a legacy unscoped card (NULL
    range columns) never matches a real user-selected scope, and vice versa.
    """
    if scope is None:
        return "", ()
    return (
        "AND start_date IS ? AND end_date IS ? AND list_scope IS ?",
        (
            scope.start_date.isoformat(),
            scope.end_date.isoformat(),
            scope.stored_list_scope,
        ),
    )

# Timestamps are stored as UTC ISO strings, matching the monitor's other
# tables (collected_at, created_at, ...).
def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def ensure_research_schema(connection: sqlite3.Connection) -> None:
    """Create the research card tables and indexes idempotently."""
    connection.executescript(
        """
        CREATE TABLE IF NOT EXISTS research_cards (
            id INTEGER PRIMARY KEY,
            company_id INTEGER NOT NULL,
            language TEXT NOT NULL,
            status TEXT NOT NULL,
            model_provider_fingerprint TEXT NOT NULL,
            model_name TEXT NOT NULL,
            prompt_version TEXT NOT NULL,
            schema_version TEXT NOT NULL,
            evidence_rule_version TEXT NOT NULL,
            evidence_fingerprint TEXT NOT NULL,
            content_json TEXT NOT NULL DEFAULT '',
            generated_at TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            error_code TEXT,
            FOREIGN KEY (company_id) REFERENCES companies(id) ON DELETE RESTRICT
        );

        CREATE TABLE IF NOT EXISTS research_card_evidence (
            research_card_id INTEGER NOT NULL,
            evidence_ref TEXT NOT NULL,
            information_item_id INTEGER NOT NULL,
            company_id INTEGER NOT NULL,
            event_timestamp TEXT NOT NULL,
            source TEXT NOT NULL,
            information_type TEXT NOT NULL,
            title_snapshot TEXT NOT NULL,
            url_snapshot TEXT NOT NULL,
            published_at_snapshot TEXT,
            raw_metadata_snapshot TEXT,
            position INTEGER NOT NULL,
            PRIMARY KEY (research_card_id, evidence_ref),
            FOREIGN KEY (research_card_id)
                REFERENCES research_cards(id)
                ON DELETE CASCADE
        );

        CREATE INDEX IF NOT EXISTS idx_research_cards_company_language
            ON research_cards(company_id, language, generated_at DESC);
        CREATE INDEX IF NOT EXISTS idx_research_cards_fingerprint
            ON research_cards(evidence_fingerprint);
        CREATE INDEX IF NOT EXISTS idx_research_card_evidence_item
            ON research_card_evidence(information_item_id);
        """
    )
    _migrate_research_card_scope(connection)
    connection.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_research_cards_scope
            ON research_cards(company_id, language, start_date, end_date, list_scope)
        """
    )


def _migrate_research_card_scope(connection: sqlite3.Connection) -> None:
    """Add the generation-scope columns to existing databases, idempotently.

    Older databases have no start_date/end_date/list_scope columns. Existing
    rows keep NULLs and are treated as legacy unscoped cards: they never match
    a scoped query and can never pose as the latest card for a user-selected
    range. No rows are rewritten and no fabricated ranges are backfilled.
    """
    columns = {
        str(row[1])
        for row in connection.execute("PRAGMA table_info(research_cards)")
    }
    for column in ("start_date", "end_date", "list_scope"):
        if column not in columns:
            connection.execute(
                f"ALTER TABLE research_cards ADD COLUMN {column} TEXT"
            )


class ResearchRepository:
    """Durable storage for research cards, kept separate from connector code."""

    def __init__(self, database_path: Path) -> None:
        self._database_path = database_path
        self._database_path.parent.mkdir(parents=True, exist_ok=True)
        self.recover_interrupted()

    def create_generation(
        self,
        *,
        company_id: int,
        language: str,
        evidence_fingerprint: str,
        model_provider_fingerprint: str,
        model_name: str,
        scope: Optional["ResearchScope"] = None,
    ) -> int:
        """Create a placeholder ``generating`` row to dedupe concurrent work."""
        now = _utc_now()
        with self._connect() as connection:
            cursor = connection.execute(
                """
                INSERT INTO research_cards (
                    company_id, language, status, model_provider_fingerprint,
                    model_name, prompt_version, schema_version,
                    evidence_rule_version, evidence_fingerprint, content_json,
                    generated_at, created_at, updated_at, error_code,
                    start_date, end_date, list_scope
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, '', NULL, ?, ?, NULL, ?, ?, ?)
                """,
                (
                    company_id,
                    language,
                    CARD_STATUS_GENERATING,
                    model_provider_fingerprint,
                    model_name,
                    RESEARCH_PROMPT_VERSION,
                    RESEARCH_SCHEMA_VERSION,
                    RESEARCH_EVIDENCE_RULE_VERSION,
                    evidence_fingerprint,
                    now,
                    now,
                    scope.start_date.isoformat() if scope else None,
                    scope.end_date.isoformat() if scope else None,
                    scope.stored_list_scope if scope else None,
                ),
            )
            return int(cursor.lastrowid)

    def complete_generation(
        self,
        card_id: int,
        *,
        company_id: int,
        content_json: str,
        evidence: Sequence[ResearchEvidence],
        generated_at: Optional[str] = None,
    ) -> None:
        """Mark a card completed and write its evidence snapshot."""
        now = _utc_now()
        generated = generated_at or now
        with self._connect() as connection:
            connection.execute(
                """
                UPDATE research_cards
                SET status = ?, content_json = ?, generated_at = ?,
                    updated_at = ?, error_code = NULL
                WHERE id = ?
                """,
                (CARD_STATUS_COMPLETED, content_json, generated, now, card_id),
            )
            connection.executemany(
                """
                INSERT INTO research_card_evidence (
                    research_card_id, evidence_ref, information_item_id,
                    company_id, event_timestamp, source, information_type,
                    title_snapshot, url_snapshot, published_at_snapshot,
                    raw_metadata_snapshot, position
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        card_id,
                        item.ref,
                        item.item_id,
                        company_id,
                        item.event_at.isoformat(),
                        item.source,
                        information_type_of(item.source_type),
                        item.title,
                        item.url,
                        item.published_at,
                        None,
                        position,
                    )
                    for position, item in enumerate(evidence, start=1)
                ],
            )

    def fail_generation(self, card_id: int, error_code: str) -> None:
        """Mark a card failed with a stable machine error code."""
        with self._connect() as connection:
            connection.execute(
                """
                UPDATE research_cards
                SET status = ?, updated_at = ?, error_code = ?
                WHERE id = ?
                """,
                (CARD_STATUS_FAILED, _utc_now(), error_code, card_id),
            )

    def has_in_progress(
        self,
        company_id: int,
        language: str,
        scope: Optional[ResearchScope] = None,
    ) -> bool:
        scope_sql, scope_parameters = _scope_filter(scope)
        with self._connect() as connection:
            row = connection.execute(
                f"""
                SELECT 1 FROM research_cards
                WHERE company_id = ? AND language = ? AND status = ?
                {scope_sql}
                LIMIT 1
                """,
                (company_id, language, CARD_STATUS_GENERATING, *scope_parameters),
            ).fetchone()
        return row is not None

    def recover_interrupted(self) -> int:
        """Convert stale ``generating`` rows to ``failed`` after a restart."""
        with self._connect() as connection:
            cursor = connection.execute(
                """
                UPDATE research_cards
                SET status = ?, updated_at = ?, error_code = 'generation_interrupted'
                WHERE status = ?
                """,
                (CARD_STATUS_FAILED, _utc_now(), CARD_STATUS_GENERATING),
            )
            return cursor.rowcount

    def latest_card(
        self,
        company_id: int,
        language: str,
        scope: Optional[ResearchScope] = None,
    ) -> Optional[Mapping[str, Any]]:
        """Return the most recent card for a company/language/scope, or None."""
        scope_sql, scope_parameters = _scope_filter(scope)
        with self._connect() as connection:
            row = connection.execute(
                f"""
                SELECT * FROM research_cards
                WHERE company_id = ? AND language = ?
                {scope_sql}
                ORDER BY id DESC
                LIMIT 1
                """,
                (company_id, language, *scope_parameters),
            ).fetchone()
        return dict(row) if row else None

    def latest_completed_card(
        self,
        company_id: int,
        language: str,
        scope: Optional[ResearchScope] = None,
    ) -> Optional[Mapping[str, Any]]:
        """Return the latest completed (valid) card for the scope, or None."""
        scope_sql, scope_parameters = _scope_filter(scope)
        with self._connect() as connection:
            row = connection.execute(
                f"""
                SELECT * FROM research_cards
                WHERE company_id = ? AND language = ? AND status = ?
                {scope_sql}
                ORDER BY id DESC
                LIMIT 1
                """,
                (company_id, language, CARD_STATUS_COMPLETED, *scope_parameters),
            ).fetchone()
        return dict(row) if row else None

    def card_by_id(self, card_id: int) -> Optional[Mapping[str, Any]]:
        """Return one card with its evidence snapshot, or None."""
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM research_cards WHERE id = ?",
                (card_id,),
            ).fetchone()
            if row is None:
                return None
            evidence_rows = connection.execute(
                """
                SELECT * FROM research_card_evidence
                WHERE research_card_id = ?
                ORDER BY position
                """,
                (card_id,),
            ).fetchall()
        card = dict(row)
        card["evidence"] = [dict(entry) for entry in evidence_rows]
        return card

    def evidence_snapshot(self, card_id: int) -> List[Mapping[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT * FROM research_card_evidence
                WHERE research_card_id = ?
                ORDER BY position
                """,
                (card_id,),
            ).fetchall()
        return [dict(row) for row in rows]

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(str(self._database_path))
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        try:
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()
