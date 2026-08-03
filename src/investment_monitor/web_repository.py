"""Relational queries and durable state for the local web MVP."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
import json
from pathlib import Path
import re
import sqlite3
from typing import Any, Dict, Iterable, List, Mapping, Optional, Protocol, Sequence, Tuple
from zoneinfo import ZoneInfo

from .config import UniverseEntry

EASTERN = ZoneInfo("America/New_York")
FIXED_LISTS = (
    ("holdings", "Holdings", 1),
    ("planned", "Planned Purchases", 2),
    ("watchlist", "Watchlist", 3),
)
PRODUCTION_SOURCES = ("sec",)


@dataclass(frozen=True)
class FeedFilters:
    list_slug: Optional[str] = None
    ticker: Optional[str] = None
    information_type: str = "all"
    form_type: Optional[str] = None
    start_date: Optional[date] = None
    end_date: Optional[date] = None
    read_state: str = "all"
    amendment: str = "all"
    query: Optional[str] = None
    page: int = 1
    page_size: int = 25

    def __post_init__(self) -> None:
        if self.page < 1:
            raise ValueError("page must be at least 1")
        if not 1 <= self.page_size <= 100:
            raise ValueError("page_size must be between 1 and 100")
        if self.start_date and self.end_date and self.start_date > self.end_date:
            raise ValueError("start_date must not be after end_date")
        if self.read_state not in {"all", "read", "unread"}:
            raise ValueError("read_state must be all, read, or unread")
        if self.amendment not in {"all", "yes", "no"}:
            raise ValueError("amendment must be all, yes, or no")
        if self.information_type not in {"all", "filings", "news", "community"}:
            raise ValueError("unsupported information_type")


@dataclass(frozen=True)
class PageResult:
    items: Tuple[Mapping[str, Any], ...]
    total: int
    page: int
    page_size: int

    @property
    def pages(self) -> int:
        return max(1, (self.total + self.page_size - 1) // self.page_size)


class CompanyResolver(Protocol):
    """Source-neutral company identity lookup used by list management."""

    def resolve(self, ticker: str) -> Optional[Mapping[str, str]]:
        ...


class WebRepository:
    """Web-facing SQLite operations kept separate from connector code."""

    def __init__(
        self,
        database_path: Path,
        *,
        migration_path: Optional[Path] = None,
        allowed_sources: Sequence[str] = PRODUCTION_SOURCES,
    ) -> None:
        self._database_path = database_path
        self._allowed_sources = tuple(allowed_sources)
        self._migration_path = migration_path or (
            Path(__file__).parent / "migrations" / "001_web_mvp.sql"
        )
        self.initialize()

    def initialize(self) -> None:
        self._database_path.parent.mkdir(parents=True, exist_ok=True)
        sql = self._migration_path.read_text(encoding="utf-8")
        with self._connect() as connection:
            connection.executescript(sql)
            connection.executemany(
                """
                INSERT INTO system_lists (slug, name, position, is_fixed)
                VALUES (?, ?, ?, 1)
                ON CONFLICT(slug) DO UPDATE SET
                    name = excluded.name,
                    position = excluded.position,
                    is_fixed = 1
                """,
                FIXED_LISTS,
            )
            connection.execute(
                "INSERT OR IGNORE INTO app_settings (key, value) VALUES ('page_size', '25')"
            )
            connection.execute("PRAGMA optimize")

    def import_universe(self, entries: Iterable[UniverseEntry]) -> bool:
        """Import the CSV once; later web memberships remain authoritative."""
        now = _utc_now()
        with self._connect() as connection:
            imported = connection.execute(
                "SELECT value FROM app_settings WHERE key = 'initial_universe_imported'"
            ).fetchone()
            if imported and imported["value"] == "true":
                return False
            for entry in entries:
                item_row = connection.execute(
                    """
                    SELECT i.issuer, i.raw_metadata
                    FROM information_items i
                    JOIN information_item_tickers t ON t.item_id = i.id
                    WHERE t.ticker = ? AND i.source = 'sec'
                    ORDER BY i.published_at DESC, i.external_id DESC
                    LIMIT 1
                    """,
                    (entry.ticker,),
                ).fetchone()
                name = str(item_row["issuer"]) if item_row else entry.ticker
                cik = ""
                if item_row:
                    try:
                        cik = str(json.loads(item_row["raw_metadata"]).get("cik") or "")
                    except (TypeError, json.JSONDecodeError):
                        cik = ""
                company_id = self._upsert_company(
                    connection,
                    ticker=entry.ticker,
                    name=name,
                    exchange="Unavailable",
                    cik=cik,
                    mapping_status="mapped" if cik else "unmapped",
                    now=now,
                )
                self._add_membership(connection, company_id, entry.list_type, now)
            connection.execute(
                """
                INSERT INTO app_settings (key, value)
                VALUES ('initial_universe_imported', 'true')
                ON CONFLICT(key) DO UPDATE SET value = excluded.value
                """
            )
        return True

    def fixed_lists(self) -> List[Mapping[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT id, slug, name, position FROM system_lists ORDER BY position"
            ).fetchall()
        return [dict(row) for row in rows]

    def companies(self, list_slug: Optional[str] = None) -> List[Mapping[str, Any]]:
        parameters: List[Any] = []
        list_condition = ""
        if list_slug:
            list_condition = "HAVING SUM(CASE WHEN l.slug = ? THEN 1 ELSE 0 END) > 0"
            parameters.append(list_slug)
        with self._connect() as connection:
            rows = connection.execute(
                f"""
                SELECT c.id, c.ticker, c.name, c.exchange, c.cik,
                       c.mapping_status,
                       GROUP_CONCAT(l.slug, ',') AS list_slugs
                FROM companies c
                LEFT JOIN company_list_memberships m ON m.company_id = c.id
                LEFT JOIN system_lists l ON l.id = m.list_id
                GROUP BY c.id
                {list_condition}
                ORDER BY c.ticker
                """,
                parameters,
            ).fetchall()
        return [_company_dict(row) for row in rows]

    def active_tickers(self) -> Tuple[str, ...]:
        """Return companies that currently belong to at least one fixed list."""
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT DISTINCT c.ticker
                FROM companies c
                JOIN company_list_memberships m ON m.company_id = c.id
                ORDER BY c.ticker
                """
            ).fetchall()
        return tuple(str(row["ticker"]) for row in rows)

    def active_tickers_without_source_items(self, source: str) -> Tuple[str, ...]:
        """Return active companies that have never stored an item from a source."""
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT DISTINCT c.ticker
                FROM companies c
                JOIN company_list_memberships m ON m.company_id = c.id
                WHERE NOT EXISTS (
                    SELECT 1
                    FROM information_item_tickers it
                    JOIN information_items i ON i.id = it.item_id
                    WHERE it.ticker = c.ticker AND i.source = ?
                )
                ORDER BY c.ticker
                """,
                (source,),
            ).fetchall()
        return tuple(str(row["ticker"]) for row in rows)

    def add_companies_batch(
        self,
        raw_tickers: str,
        list_slugs: Sequence[str],
        resolver: CompanyResolver,
    ) -> Mapping[str, Any]:
        tickers = _normalize_tickers(raw_tickers)
        if not tickers:
            raise ValueError("Enter at least one ticker")
        valid_lists = {row["slug"] for row in self.fixed_lists()}
        destinations = tuple(dict.fromkeys(list_slugs))
        if not destinations or any(slug not in valid_lists for slug in destinations):
            raise ValueError("Select at least one valid destination list")

        added: List[Mapping[str, Any]] = []
        already_present: List[Mapping[str, Any]] = []
        failed: List[Mapping[str, str]] = []
        now = _utc_now()
        with self._connect() as connection:
            for ticker in tickers:
                mapping = resolver.resolve(ticker)
                existing = connection.execute(
                    "SELECT * FROM companies WHERE ticker = ?", (ticker,)
                ).fetchone()
                if mapping is None and existing is None:
                    failed.append({"ticker": ticker, "error": "Ticker could not be mapped to an SEC CIK."})
                    continue
                identity = mapping or dict(existing)
                company_id = self._upsert_company(
                    connection,
                    ticker=ticker,
                    name=str(identity.get("name") or ticker),
                    exchange=str(identity.get("exchange") or "Unavailable"),
                    cik=str(identity.get("cik") or ""),
                    mapping_status=str(identity.get("mapping_status") or "mapped"),
                    now=now,
                )
                created_lists = []
                existing_lists = []
                for slug in destinations:
                    if self._add_membership(connection, company_id, slug, now):
                        created_lists.append(slug)
                    else:
                        existing_lists.append(slug)
                result = {
                    "ticker": ticker,
                    "name": str(identity.get("name") or ticker),
                    "exchange": str(identity.get("exchange") or "Unavailable"),
                    "cik": str(identity.get("cik") or ""),
                    "mapping_status": str(identity.get("mapping_status") or "mapped"),
                    "lists": created_lists or existing_lists,
                }
                (added if created_lists else already_present).append(result)
        return {"added": added, "already_present": already_present, "failed": failed}

    def remove_membership(self, ticker: str, list_slug: str) -> bool:
        with self._connect() as connection:
            cursor = connection.execute(
                """
                DELETE FROM company_list_memberships
                WHERE company_id = (SELECT id FROM companies WHERE ticker = ?)
                  AND list_id = (SELECT id FROM system_lists WHERE slug = ?)
                """,
                (ticker.upper(), list_slug),
            )
        return cursor.rowcount > 0

    def remove_all_memberships(self, ticker: str) -> int:
        with self._connect() as connection:
            cursor = connection.execute(
                """
                DELETE FROM company_list_memberships
                WHERE company_id = (SELECT id FROM companies WHERE ticker = ?)
                """,
                (ticker.upper(),),
            )
        return cursor.rowcount

    def query_feed(self, filters: FeedFilters) -> PageResult:
        where_sql, parameters = self._feed_where(filters)
        source_placeholders = ",".join("?" for _ in self._allowed_sources)
        if not source_placeholders:
            return PageResult((), 0, 1, filters.page_size)
        sql = f"""
            SELECT i.id, i.source, i.source_type, i.external_id, i.issuer,
                   i.published_at, i.title, i.document_type, i.url,
                   i.collected_at, i.raw_metadata,
                   COALESCE(r.is_read, 0) AS is_read,
                   c.ticker, c.name AS company_name, c.exchange, c.cik,
                   GROUP_CONCAT(DISTINCT l.slug) AS list_slugs
            FROM information_items i
            JOIN information_item_tickers it ON it.item_id = i.id
            JOIN companies c ON c.ticker = it.ticker
            JOIN company_list_memberships m ON m.company_id = c.id
            JOIN system_lists l ON l.id = m.list_id
            LEFT JOIN information_read_state r ON r.item_id = i.id
            WHERE i.source IN ({source_placeholders})
              AND COALESCE(json_extract(i.raw_metadata, '$.generated'), 0) != 1
              {where_sql}
            GROUP BY i.id, c.id
            ORDER BY {self._effective_timestamp_sql()} DESC,
                     i.external_id DESC, i.source DESC, i.id DESC
            LIMIT ? OFFSET ?
        """
        count_sql = f"""
            SELECT COUNT(DISTINCT i.id) AS total
            FROM information_items i
            JOIN information_item_tickers it ON it.item_id = i.id
            JOIN companies c ON c.ticker = it.ticker
            JOIN company_list_memberships m ON m.company_id = c.id
            JOIN system_lists l ON l.id = m.list_id
            LEFT JOIN information_read_state r ON r.item_id = i.id
            WHERE i.source IN ({source_placeholders})
              AND COALESCE(json_extract(i.raw_metadata, '$.generated'), 0) != 1
              {where_sql}
        """
        base_parameters = list(self._allowed_sources) + parameters
        with self._connect() as connection:
            total = int(connection.execute(count_sql, base_parameters).fetchone()["total"])
            pages = max(1, (total + filters.page_size - 1) // filters.page_size)
            page = min(filters.page, pages)
            offset = (page - 1) * filters.page_size
            rows = connection.execute(
                sql,
                base_parameters + [filters.page_size, offset],
            ).fetchall()
        return PageResult(
            tuple(self._feed_item(row) for row in rows),
            total,
            page,
            filters.page_size,
        )

    def counts(self, selected_date: date) -> Mapping[str, Any]:
        start_utc, end_utc = _eastern_day_bounds(selected_date)
        today_filters = FeedFilters(
            information_type="filings",
            start_date=selected_date,
            end_date=selected_date,
            page_size=1,
        )
        today_total = self.query_feed(today_filters).total
        with self._connect() as connection:
            company_count = int(connection.execute(
                "SELECT COUNT(DISTINCT company_id) AS count FROM company_list_memberships"
            ).fetchone()["count"])
            unread_total = self._count_unread(connection, None)
            list_rows = connection.execute(
                "SELECT slug, name FROM system_lists ORDER BY position"
            ).fetchall()
            list_counts = {
                row["slug"]: self._count_unread(connection, str(row["slug"]))
                for row in list_rows
            }
        return {
            "companies": company_count,
            "unread": unread_total,
            "filings": today_total,
            "list_unread": list_counts,
            "start_utc": start_utc.isoformat(),
            "end_utc": end_utc.isoformat(),
        }

    def set_read(self, item_ids: Sequence[int], is_read: bool) -> int:
        unique_ids = tuple(dict.fromkeys(int(item_id) for item_id in item_ids))
        if not unique_ids:
            return 0
        now = _utc_now()
        with self._connect() as connection:
            valid_ids = {
                int(row["id"])
                for row in connection.execute(
                    f"SELECT id FROM information_items WHERE id IN ({','.join('?' for _ in unique_ids)})",
                    unique_ids,
                ).fetchall()
            }
            connection.executemany(
                """
                INSERT INTO information_read_state (item_id, is_read, updated_at)
                VALUES (?, ?, ?)
                ON CONFLICT(item_id) DO UPDATE SET
                    is_read = excluded.is_read,
                    updated_at = excluded.updated_at
                """,
                ((item_id, int(is_read), now) for item_id in valid_ids),
            )
        return len(valid_ids)

    def bulk_set_read(self, filters: FeedFilters, is_read: bool) -> int:
        scoped = FeedFilters(**{**filters.__dict__, "page": 1, "page_size": 100})
        ids: List[int] = []
        page = 1
        while True:
            current = FeedFilters(**{**scoped.__dict__, "page": page})
            result = self.query_feed(current)
            ids.extend(int(item["id"]) for item in result.items)
            if page >= result.pages:
                break
            page += 1
        return self.set_read(ids, is_read)

    def source_statuses(
        self,
        *,
        now: Optional[datetime] = None,
        stale_after: timedelta = timedelta(hours=36),
    ) -> List[Mapping[str, Any]]:
        with self._connect() as connection:
            sec_row = connection.execute(
                "SELECT MAX(collected_at) AS latest FROM information_items WHERE source = 'sec'"
            ).fetchone()
            run_row = connection.execute(
                "SELECT * FROM ingestion_runs WHERE source = 'sec' ORDER BY started_at DESC LIMIT 1"
            ).fetchone()
            success_row = connection.execute(
                """
                SELECT MAX(finished_at) AS latest
                FROM ingestion_runs
                WHERE source = 'sec' AND status IN ('success', 'partial')
                """
            ).fetchone()
            failure_row = connection.execute(
                """
                SELECT error_summary
                FROM ingestion_runs
                WHERE source = 'sec' AND status IN ('failure', 'partial')
                ORDER BY started_at DESC LIMIT 1
                """
            ).fetchone()
        latest = (success_row["latest"] if success_row else None) or (
            sec_row["latest"] if sec_row else None
        )
        current_time = now or datetime.now(timezone.utc)
        if current_time.tzinfo is None:
            current_time = current_time.replace(tzinfo=timezone.utc)
        is_stale = bool(
            latest
            and current_time.astimezone(timezone.utc) - _parse_datetime(str(latest)).astimezone(timezone.utc)
            > stale_after
        )
        sec_enabled = "sec" in self._allowed_sources
        if not sec_enabled:
            sec_status = "not_connected"
        elif run_row and run_row["status"] == "failure":
            sec_status = "temporarily_unavailable"
        elif latest and is_stale:
            sec_status = "stale"
        else:
            sec_status = "connected" if latest else "unavailable"
        statuses: List[Mapping[str, Any]] = [
            {
                "type": "Filings",
                "provider": "SEC EDGAR" if sec_enabled else None,
                "status": sec_status,
                "latest_success": latest,
                "latest_attempt": (run_row["finished_at"] or run_row["started_at"]) if run_row else None,
                "last_failure": failure_row["error_summary"] if failure_row else None,
                "is_stale": is_stale,
                "stale_after_hours": int(stale_after.total_seconds() // 3600),
            },
        ]
        statuses.extend(self._non_sec_source_statuses())
        return statuses

    def _non_sec_source_statuses(self) -> List[Mapping[str, Any]]:
        result: List[Mapping[str, Any]] = []
        if not self._allowed_sources:
            allowed_clause = "0"
            parameters: Sequence[str] = ()
        else:
            allowed_clause = f"source IN ({','.join('?' for _ in self._allowed_sources)})"
            parameters = self._allowed_sources
        with self._connect() as connection:
            for label, source_type in (("News", "news"), ("Community", "community")):
                row = connection.execute(
                    f"""
                    SELECT GROUP_CONCAT(DISTINCT source) AS providers,
                           MAX(collected_at) AS latest
                    FROM information_items
                    WHERE {allowed_clause}
                      AND source_type = ?
                      AND COALESCE(json_extract(raw_metadata, '$.generated'), 0) != 1
                    """,
                    tuple(parameters) + (source_type,),
                ).fetchone()
                connected = bool(row and row["providers"])
                result.append({
                    "type": label,
                    "provider": str(row["providers"]) if connected else None,
                    "status": "connected" if connected else "not_connected",
                    "latest_success": row["latest"] if connected else None,
                    "latest_attempt": None,
                    "last_failure": None,
                })
        return result

    def available_source_types(self) -> Tuple[str, ...]:
        """Return stored source types belonging to production-enabled sources."""
        if not self._allowed_sources:
            return ()
        placeholders = ",".join("?" for _ in self._allowed_sources)
        with self._connect() as connection:
            rows = connection.execute(
                f"""
                SELECT DISTINCT source_type
                FROM information_items
                WHERE source IN ({placeholders})
                  AND COALESCE(json_extract(raw_metadata, '$.generated'), 0) != 1
                ORDER BY source_type
                """,
                self._allowed_sources,
            ).fetchall()
        return tuple(str(row["source_type"]) for row in rows)

    def activity(
        self,
        *,
        source: Optional[str] = None,
        status: Optional[str] = None,
        start_date: Optional[date] = None,
        end_date: Optional[date] = None,
    ) -> Mapping[str, Any]:
        if start_date and end_date and start_date > end_date:
            raise ValueError("start_date must not be after end_date")
        common_conditions = []
        common_parameters: List[Any] = []
        if source:
            common_conditions.append("source = ?")
            common_parameters.append(source)
        if status:
            common_conditions.append("status = ?")
            common_parameters.append(status)
        run_conditions = list(common_conditions)
        log_conditions = list(common_conditions)
        run_parameters = list(common_parameters)
        log_parameters = list(common_parameters)
        if start_date:
            start_utc, _ = _eastern_day_bounds(start_date)
            run_conditions.append("datetime(started_at) >= datetime(?)")
            log_conditions.append("datetime(occurred_at) >= datetime(?)")
            run_parameters.append(start_utc.isoformat())
            log_parameters.append(start_utc.isoformat())
        if end_date:
            _, end_utc = _eastern_day_bounds(end_date)
            run_conditions.append("datetime(started_at) < datetime(?)")
            log_conditions.append("datetime(occurred_at) < datetime(?)")
            run_parameters.append(end_utc.isoformat())
            log_parameters.append(end_utc.isoformat())
        run_where = "WHERE " + " AND ".join(run_conditions) if run_conditions else ""
        log_where = "WHERE " + " AND ".join(log_conditions) if log_conditions else ""
        with self._connect() as connection:
            runs = [dict(row) for row in connection.execute(
                f"SELECT * FROM ingestion_runs {run_where} ORDER BY started_at DESC LIMIT 50",
                run_parameters,
            ).fetchall()]
            logs = [dict(row) for row in connection.execute(
                f"SELECT * FROM ingestion_logs {log_where} ORDER BY occurred_at DESC, id DESC LIMIT 100",
                log_parameters,
            ).fetchall()]
        return {"runs": runs, "logs": logs}

    def record_collection_events(self, events: Sequence[Any]) -> None:
        """Persist completed pipeline events without coupling the pipeline to SQLite."""
        grouped: Dict[str, List[Any]] = {}
        for event in events:
            grouped.setdefault(str(event.source), []).append(event)
        with self._connect() as connection:
            for source, source_events in grouped.items():
                failures = [event for event in source_events if event.status == "failure"]
                successful = [event for event in source_events if event.status != "failure"]
                status = "failure" if not successful else "partial" if failures else "success"
                error_summary = "; ".join(
                    f"{event.ticker}: {event.error_message}" for event in failures
                ) or None
                cursor = connection.execute(
                    """
                    INSERT INTO ingestion_runs (
                        source, started_at, finished_at, status,
                        companies_processed, successful_companies, failed_companies,
                        records_fetched, records_inserted, duplicate_records, error_summary
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        source,
                        min(event.started_at for event in source_events).isoformat(),
                        max(event.finished_at for event in source_events).isoformat(),
                        status,
                        len(source_events),
                        len(successful),
                        len(failures),
                        sum(event.records_read for event in source_events),
                        sum(getattr(event, "records_inserted", event.records_written) for event in source_events),
                        sum(getattr(event, "records_updated", event.duplicate_records) for event in source_events),
                        error_summary,
                    ),
                )
                if cursor.lastrowid is None:
                    raise RuntimeError("SQLite did not return an ingestion run id.")
                run_id = int(cursor.lastrowid)
                connection.executemany(
                    """
                    INSERT INTO ingestion_logs (
                        run_id, occurred_at, operation, source, ticker, status,
                        records_read, records_written, error_message
                    ) VALUES (?, ?, 'collect', ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        (
                            run_id,
                            event.finished_at.isoformat(),
                            source,
                            event.ticker,
                            event.status,
                            event.records_read,
                            event.records_written,
                            event.error_message,
                        )
                        for event in source_events
                    ),
                )

    def setting(self, key: str, default: str) -> str:
        with self._connect() as connection:
            row = connection.execute("SELECT value FROM app_settings WHERE key = ?", (key,)).fetchone()
        return str(row["value"]) if row else default

    def last_daily_sync_date(self) -> Optional[date]:
        value = self.setting("last_daily_sync_date", "")
        if not value:
            return None
        try:
            return date.fromisoformat(value)
        except ValueError:
            return None

    def mark_daily_sync_attempt(self, attempted_on: date) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO app_settings (key, value)
                VALUES ('last_daily_sync_date', ?)
                ON CONFLICT(key) DO UPDATE SET value = excluded.value
                """,
                (attempted_on.isoformat(),),
            )

    def set_setting(self, key: str, value: str) -> None:
        if key != "page_size" or value not in {"10", "25", "50"}:
            raise ValueError("Unsupported setting value")
        with self._connect() as connection:
            connection.execute(
                "INSERT INTO app_settings (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                (key, value),
            )

    def _feed_where(self, filters: FeedFilters) -> Tuple[str, List[Any]]:
        conditions: List[str] = []
        parameters: List[Any] = []
        if filters.list_slug:
            conditions.append(
                """
                EXISTS (
                    SELECT 1
                    FROM company_list_memberships scoped_membership
                    JOIN system_lists scoped_list ON scoped_list.id = scoped_membership.list_id
                    WHERE scoped_membership.company_id = c.id
                      AND scoped_list.slug = ?
                )
                """
            )
            parameters.append(filters.list_slug)
        if filters.ticker:
            conditions.append("c.ticker = ?")
            parameters.append(filters.ticker.upper())
        if filters.information_type == "filings":
            conditions.append("i.source_type = 'regulatory_filing'")
        elif filters.information_type == "news":
            conditions.append("i.source_type = 'news'")
        elif filters.information_type == "community":
            conditions.append("i.source_type = 'community'")
        if filters.form_type:
            conditions.append("i.document_type = ?")
            parameters.append(filters.form_type)
        if filters.start_date:
            start_utc, _ = _eastern_day_bounds(filters.start_date)
            conditions.append(f"{self._effective_timestamp_sql()} >= datetime(?)")
            parameters.append(start_utc.isoformat())
        if filters.end_date:
            _, end_utc = _eastern_day_bounds(filters.end_date)
            conditions.append(f"{self._effective_timestamp_sql()} < datetime(?)")
            parameters.append(end_utc.isoformat())
        if filters.read_state == "read":
            conditions.append("COALESCE(r.is_read, 0) = 1")
        elif filters.read_state == "unread":
            conditions.append("COALESCE(r.is_read, 0) = 0")
        if filters.amendment == "yes":
            conditions.append("i.document_type LIKE '%/A'")
        elif filters.amendment == "no":
            conditions.append("i.document_type NOT LIKE '%/A'")
        if filters.query:
            like = f"%{filters.query.strip()}%"
            conditions.append(
                "(c.ticker LIKE ? OR c.name LIKE ? OR i.title LIKE ? OR i.document_type LIKE ? OR i.external_id LIKE ?)"
            )
            parameters.extend([like] * 5)
        return (" AND " + " AND ".join(conditions) if conditions else "", parameters)

    def _feed_item(self, row: sqlite3.Row) -> Mapping[str, Any]:
        raw_metadata = json.loads(row["raw_metadata"])
        effective = raw_metadata.get("acceptanceDateTime") or row["published_at"]
        effective_dt = _parse_datetime(str(effective))
        list_slugs = sorted((row["list_slugs"] or "").split(","))
        return {
            "id": int(row["id"]),
            "source": row["source"],
            "source_label": "SEC EDGAR" if row["source"] == "sec" else row["source"],
            "source_type": row["source_type"],
            "external_id": row["external_id"],
            "issuer": row["issuer"],
            "company_name": row["company_name"],
            "ticker": row["ticker"],
            "exchange": row["exchange"],
            "cik": row["cik"],
            "published_at": row["published_at"],
            "effective_at": effective_dt.isoformat(),
            "effective_et": effective_dt.astimezone(EASTERN).strftime("%b %-d, %Y %-I:%M %p ET"),
            "title": row["title"],
            "document_type": row["document_type"],
            "url": row["url"],
            "is_read": bool(row["is_read"]),
            "is_amendment": str(row["document_type"]).endswith("/A"),
            "list_slugs": list_slugs,
            "raw_metadata": raw_metadata,
        }

    def _count_unread(self, connection: sqlite3.Connection, list_slug: Optional[str]) -> int:
        source_placeholders = ",".join("?" for _ in self._allowed_sources)
        parameters: List[Any] = list(self._allowed_sources)
        list_sql = ""
        if list_slug:
            list_sql = "AND l.slug = ?"
            parameters.append(list_slug)
        row = connection.execute(
            f"""
            SELECT COUNT(DISTINCT i.id) AS count
            FROM information_items i
            JOIN information_item_tickers it ON it.item_id = i.id
            JOIN companies c ON c.ticker = it.ticker
            JOIN company_list_memberships m ON m.company_id = c.id
            JOIN system_lists l ON l.id = m.list_id
            LEFT JOIN information_read_state r ON r.item_id = i.id
            WHERE i.source IN ({source_placeholders})
              AND COALESCE(json_extract(i.raw_metadata, '$.generated'), 0) != 1
              AND COALESCE(r.is_read, 0) = 0
              {list_sql}
            """,
            parameters,
        ).fetchone()
        return int(row["count"])

    @staticmethod
    def _effective_timestamp_sql() -> str:
        return "COALESCE(datetime(json_extract(i.raw_metadata, '$.acceptanceDateTime')), datetime(i.published_at))"

    def _upsert_company(
        self,
        connection: sqlite3.Connection,
        *,
        ticker: str,
        name: str,
        exchange: str,
        cik: str,
        mapping_status: str,
        now: str,
    ) -> int:
        connection.execute(
            """
            INSERT INTO companies (ticker, name, exchange, cik, mapping_status, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(ticker) DO UPDATE SET
                name = CASE WHEN excluded.name != '' THEN excluded.name ELSE companies.name END,
                exchange = CASE WHEN excluded.exchange != '' THEN excluded.exchange ELSE companies.exchange END,
                cik = CASE WHEN excluded.cik != '' THEN excluded.cik ELSE companies.cik END,
                mapping_status = excluded.mapping_status,
                updated_at = excluded.updated_at
            """,
            (ticker, name, exchange, cik, mapping_status, now, now),
        )
        return int(connection.execute("SELECT id FROM companies WHERE ticker = ?", (ticker,)).fetchone()["id"])

    @staticmethod
    def _add_membership(connection: sqlite3.Connection, company_id: int, list_slug: str, now: str) -> bool:
        cursor = connection.execute(
            """
            INSERT OR IGNORE INTO company_list_memberships (company_id, list_id, created_at)
            SELECT ?, id, ? FROM system_lists WHERE slug = ?
            """,
            (company_id, now, list_slug),
        )
        return cursor.rowcount > 0

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(str(self._database_path))
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        return connection


def _normalize_tickers(raw: str) -> Tuple[str, ...]:
    parts = re.split(r"[\s,]+", raw.strip())
    normalized = []
    for part in parts:
        ticker = part.strip().upper()
        if ticker and ticker not in normalized:
            normalized.append(ticker)
    return tuple(normalized)


def _company_dict(row: sqlite3.Row) -> Mapping[str, Any]:
    return {
        "id": int(row["id"]),
        "ticker": row["ticker"],
        "name": row["name"],
        "exchange": row["exchange"],
        "cik": row["cik"],
        "mapping_status": row["mapping_status"],
        "list_slugs": sorted((row["list_slugs"] or "").split(",")) if row["list_slugs"] else [],
    }


def _parse_datetime(value: str) -> datetime:
    normalized = value.replace("Z", "+00:00")
    parsed = datetime.fromisoformat(normalized)
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _eastern_day_bounds(day: date) -> Tuple[datetime, datetime]:
    start_et = datetime.combine(day, time.min, tzinfo=EASTERN)
    next_day = date.fromordinal(day.toordinal() + 1)
    end_et = datetime.combine(next_day, time.min, tzinfo=EASTERN)
    return start_et.astimezone(timezone.utc), end_et.astimezone(timezone.utc)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()
