"""SQLite implementation of the generic information repository."""

from __future__ import annotations

from contextlib import contextmanager
from datetime import date, datetime
import json
from pathlib import Path
import sqlite3
from typing import Iterator, Iterable, List, Optional, Tuple

from .models import InformationItem
from .repository import SaveResult


class SQLiteInformationRepository:
    """Persist standardized information items in a local SQLite database."""

    def __init__(self, database_path: Path) -> None:
        self._database_path = database_path
        self._database_path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def save(self, items: Iterable[InformationItem]) -> SaveResult:
        """Upsert items using (source, external_id) as their identity."""
        inserted = 0
        updated = 0
        with self._connect() as connection:
            for item in items:
                existing_row = connection.execute(
                    """
                    SELECT id
                    FROM information_items
                    WHERE source = ? AND external_id = ?
                    """,
                    (item.source, item.external_id),
                ).fetchone()

                if existing_row is None:
                    cursor = connection.execute(
                        """
                        INSERT INTO information_items (
                            source,
                            source_type,
                            external_id,
                            issuer,
                            published_at,
                            title,
                            document_type,
                            url,
                            collected_at,
                            raw_metadata
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        _item_values(item),
                    )
                    if cursor.lastrowid is None:
                        raise RuntimeError("SQLite did not return an inserted item id.")
                    item_id = int(cursor.lastrowid)
                    inserted += 1
                else:
                    item_id = int(existing_row["id"])
                    connection.execute(
                        """
                        UPDATE information_items
                        SET source_type = ?,
                            issuer = ?,
                            published_at = ?,
                            title = ?,
                            document_type = ?,
                            url = ?,
                            collected_at = ?,
                            raw_metadata = ?
                        WHERE id = ?
                        """,
                        (
                            item.source_type,
                            item.issuer,
                            item.published_at.isoformat(),
                            item.title,
                            item.document_type,
                            item.url,
                            item.collected_at.isoformat(),
                            json.dumps(dict(item.raw_metadata), sort_keys=True),
                            item_id,
                        ),
                    )
                    connection.execute(
                        "DELETE FROM information_item_tickers WHERE item_id = ?",
                        (item_id,),
                    )
                    updated += 1

                connection.executemany(
                    """
                    INSERT INTO information_item_tickers (item_id, ticker)
                    VALUES (?, ?)
                    """,
                    ((item_id, ticker) for ticker in item.tickers),
                )

        return SaveResult(inserted=inserted, updated=updated)

    def query(
        self,
        *,
        ticker: Optional[str] = None,
        source: Optional[str] = None,
        source_type: Optional[str] = None,
        start_date: Optional[date] = None,
        end_date: Optional[date] = None,
    ) -> List[InformationItem]:
        """Query stored items using inclusive date boundaries."""
        if start_date is not None and end_date is not None:
            if start_date > end_date:
                raise ValueError("start_date must not be after end_date.")

        conditions: List[str] = []
        parameters: List[str] = []
        if ticker is not None:
            conditions.append(
                """
                EXISTS (
                    SELECT 1
                    FROM information_item_tickers matching_ticker
                    WHERE matching_ticker.item_id = information_items.id
                      AND matching_ticker.ticker = ?
                )
                """
            )
            parameters.append(ticker.strip().upper())
        if source is not None:
            conditions.append("source = ?")
            parameters.append(source)
        if source_type is not None:
            conditions.append("source_type = ?")
            parameters.append(source_type)
        if start_date is not None:
            conditions.append("date(published_at) >= date(?)")
            parameters.append(start_date.isoformat())
        if end_date is not None:
            conditions.append("date(published_at) <= date(?)")
            parameters.append(end_date.isoformat())

        where_clause = (
            "WHERE " + " AND ".join(conditions) if conditions else ""
        )
        sql = f"""
            SELECT *
            FROM information_items
            {where_clause}
            ORDER BY published_at ASC, source ASC, external_id ASC
        """

        with self._connect() as connection:
            rows = connection.execute(sql, parameters).fetchall()
            return [
                self._row_to_item(connection, row)
                for row in rows
            ]

    def count(self) -> int:
        """Return the number of unique stored information items."""
        with self._connect() as connection:
            row = connection.execute(
                "SELECT COUNT(*) AS item_count FROM information_items"
            ).fetchone()
        return int(row["item_count"])

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS information_items (
                    id INTEGER PRIMARY KEY,
                    source TEXT NOT NULL,
                    source_type TEXT NOT NULL,
                    external_id TEXT NOT NULL,
                    issuer TEXT NOT NULL,
                    published_at TEXT NOT NULL,
                    title TEXT NOT NULL,
                    document_type TEXT NOT NULL,
                    url TEXT NOT NULL,
                    collected_at TEXT NOT NULL,
                    raw_metadata TEXT NOT NULL,
                    UNIQUE (source, external_id)
                );

                CREATE TABLE IF NOT EXISTS information_item_tickers (
                    item_id INTEGER NOT NULL,
                    ticker TEXT NOT NULL,
                    PRIMARY KEY (item_id, ticker),
                    FOREIGN KEY (item_id)
                        REFERENCES information_items(id)
                        ON DELETE CASCADE
                );

                CREATE INDEX IF NOT EXISTS idx_information_items_source
                    ON information_items(source);
                CREATE INDEX IF NOT EXISTS idx_information_items_source_type
                    ON information_items(source_type);
                CREATE INDEX IF NOT EXISTS idx_information_items_published_at
                    ON information_items(published_at);
                CREATE INDEX IF NOT EXISTS idx_item_tickers_ticker
                    ON information_item_tickers(ticker);
                """
            )

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

    @staticmethod
    def _row_to_item(
        connection: sqlite3.Connection,
        row: sqlite3.Row,
    ) -> InformationItem:
        ticker_rows = connection.execute(
            """
            SELECT ticker
            FROM information_item_tickers
            WHERE item_id = ?
            ORDER BY ticker ASC
            """,
            (row["id"],),
        ).fetchall()
        return InformationItem(
            source=str(row["source"]),
            source_type=str(row["source_type"]),
            external_id=str(row["external_id"]),
            tickers=tuple(str(ticker_row["ticker"]) for ticker_row in ticker_rows),
            issuer=str(row["issuer"]),
            published_at=datetime.fromisoformat(str(row["published_at"])),
            title=str(row["title"]),
            document_type=str(row["document_type"]),
            url=str(row["url"]),
            collected_at=datetime.fromisoformat(str(row["collected_at"])),
            raw_metadata=json.loads(str(row["raw_metadata"])),
        )


def _item_values(item: InformationItem) -> Tuple[str, ...]:
    return (
        item.source,
        item.source_type,
        item.external_id,
        item.issuer,
        item.published_at.isoformat(),
        item.title,
        item.document_type,
        item.url,
        item.collected_at.isoformat(),
        json.dumps(dict(item.raw_metadata), sort_keys=True),
    )
