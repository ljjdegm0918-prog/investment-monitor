"""Official EDINET API v2 metadata, watchlist, sync, resolution, and downloads."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from dataclasses import asdict, dataclass, field
from datetime import date, datetime, timedelta, timezone
import csv
from hashlib import sha256
from io import BytesIO, TextIOWrapper
import json
import logging
import os
from pathlib import Path
import sqlite3
import threading
import time
from typing import Any, Callable, Dict, Iterable, Iterator, List, Mapping, Optional, Sequence, Tuple
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlsplit
from urllib.request import Request, urlopen
import zipfile
from zoneinfo import ZoneInfo

from ...connectors.base import ConnectorUnavailableError, SecretField
from ...models import CollectionRequest, InformationItem, MARKET_JP

LOGGER = logging.getLogger(__name__)
JAPAN_TIME = ZoneInfo("Asia/Tokyo")
DEFAULT_BASE_URL = "https://api.edinet-fsa.go.jp/api/v2"
OFFICIAL_CODE_LIST_URL = (
    "https://disclosure2dl.edinet-fsa.go.jp/searchdocument/codelist/Edinetcode.zip"
)
RETRYABLE_STATUS_CODES = frozenset({429, 500, 502, 503, 504})
ROLE_FIELDS = (
    ("filer", "edinetCode"), ("issuer", "issuerEdinetCode"),
    ("subject", "subjectEdinetCode"), ("subsidiary", "subsidiaryEdinetCode"),
)


class EDINETError(Exception):
    """Base EDINET error."""


class EDINETRequestError(EDINETError):
    def __init__(self, message: str, status_code: Optional[int] = None) -> None:
        super().__init__(message)
        self.status_code = status_code


class EDINETDataError(EDINETError):
    """Official response did not satisfy the documented shape."""


@dataclass(frozen=True)
class EDINETCompanyInput:
    edinet_code: Optional[str] = None
    sec_code: Optional[str] = None
    jcn: Optional[str] = None
    name: Optional[str] = None


@dataclass(frozen=True)
class ResolvedCompany:
    edinet_code: str
    filer_name: str
    sec_code: Optional[str] = None
    jcn: Optional[str] = None


@dataclass(frozen=True)
class UnresolvedCompany:
    input: Mapping[str, Optional[str]]
    reason: str
    candidates: Tuple[str, ...] = ()


@dataclass(frozen=True)
class EDINETDateError:
    file_date: date
    message: str
    retryable: bool


@dataclass(frozen=True)
class EDINETDisclosure:
    doc_id: str
    submit_datetime: datetime
    file_date: date
    filer_name: str
    edinet_code: Optional[str]
    sec_code: Optional[str]
    jcn: Optional[str]
    doc_type_code: Optional[str]
    doc_description: Optional[str]
    match_roles: Tuple[str, ...] = ()
    matched_edinet_codes: Tuple[str, ...] = ()
    matched_sec_codes: Tuple[str, ...] = ()
    period_start: Optional[date] = None
    period_end: Optional[date] = None
    issuer_edinet_code: Optional[str] = None
    subject_edinet_code: Optional[str] = None
    subsidiary_edinet_code: Optional[str] = None
    parent_doc_id: Optional[str] = None
    withdrawal_status: Optional[str] = None
    disclosure_status: Optional[str] = None
    doc_info_edit_status: Optional[str] = None
    flags: Mapping[str, Optional[str]] = field(default_factory=dict)
    raw: Mapping[str, Any] = field(default_factory=dict)

    @property
    def official_url(self) -> str:
        return f"{DEFAULT_BASE_URL}/documents/{self.doc_id}"


@dataclass(frozen=True)
class WatchlistDisclosureResult:
    items: Tuple[EDINETDisclosure, ...]
    unresolved: Tuple[UnresolvedCompany, ...]
    errors: Tuple[EDINETDateError, ...]
    partial: bool
    window_start: datetime
    window_end: datetime
    fetched_at: datetime
    counts_by_company: Mapping[str, int]
    counts_by_doc_type: Mapping[str, int]


@dataclass(frozen=True)
class DownloadResult:
    doc_id: str
    download_type: int
    path: Path
    size: int
    sha256: str
    zip_valid: Optional[bool]
    status: str


class EDINETClient:
    """Bounded official API v2 HTTP client; credentials never enter logs."""

    def __init__(self, api_key: str, *, base_url: str = DEFAULT_BASE_URL,
                 timeout: float = 15.0, max_retries: int = 3,
                 requests_per_second: float = 2.0,
                 opener: Callable[..., Any] = urlopen,
                 sleeper: Callable[[float], None] = time.sleep,
                 clock: Callable[[], float] = time.monotonic) -> None:
        if not api_key.strip():
            raise ConnectorUnavailableError("EDINET_API_KEY is not configured.")
        if timeout <= 0 or max_retries < 0 or requests_per_second <= 0:
            raise ValueError("Invalid EDINET HTTP client limits.")
        self._api_key = api_key.strip()
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout
        self._max_retries = max_retries
        self._minimum_interval = 1.0 / requests_per_second
        self._opener, self._sleeper, self._clock = opener, sleeper, clock
        self._lock = threading.Lock()
        self._last_request_at: Optional[float] = None

    @classmethod
    def from_environment(cls) -> "EDINETClient":
        return cls(
            os.environ.get("EDINET_API_KEY", ""),
            base_url=os.environ.get("EDINET_BASE_URL", DEFAULT_BASE_URL),
            timeout=_env_float("EDINET_TIMEOUT_SECONDS", 15.0),
            max_retries=_env_int("EDINET_MAX_RETRIES", 3),
            requests_per_second=_env_float("EDINET_REQUESTS_PER_SECOND", 2.0),
        )

    def list_documents(self, file_date: date) -> Mapping[str, Any]:
        return self._get_json("/documents.json", {"date": file_date.isoformat(), "type": 2})

    def download_document(self, doc_id: str, download_type: int) -> Tuple[bytes, str]:
        if not doc_id.strip() or download_type not in {1, 2, 3, 4, 5}:
            raise ValueError("doc_id and download type 1..5 are required")
        return self._request(f"/documents/{doc_id.strip()}", {"type": download_type})

    def _get_json(self, path: str, parameters: Mapping[str, Any]) -> Mapping[str, Any]:
        body, _ = self._request(path, parameters)
        try:
            payload = json.loads(body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise EDINETDataError("EDINET returned invalid JSON.") from error
        if not isinstance(payload, dict):
            raise EDINETDataError("EDINET response must be a JSON object.")
        return payload

    def _request(self, path: str, parameters: Mapping[str, Any]) -> Tuple[bytes, str]:
        return self._request_absolute(self._base_url + path, parameters)

    def _request_absolute(self, base: str, parameters: Mapping[str, Any]) -> Tuple[bytes, str]:
        if urlsplit(base).netloc != urlsplit(self._base_url).netloc:
            raise ValueError("Authenticated EDINET requests must stay on the API host")
        url = f"{base}?{urlencode(dict(parameters))}" if parameters else base
        for attempt in range(self._max_retries + 1):
            self._wait()
            request = Request(url, headers={
                "Accept": "application/json, application/zip, application/pdf, */*",
                "Ocp-Apim-Subscription-Key": self._api_key,
                "User-Agent": "InvestmentMonitor/0.1 EDINET connector",
            })
            try:
                with self._opener(request, timeout=self._timeout) as response:
                    return bytes(response.read()), str(response.headers.get("Content-Type") or "")
            except HTTPError as error:
                if error.code not in RETRYABLE_STATUS_CODES or attempt == self._max_retries:
                    raise EDINETRequestError(
                        f"EDINET request failed with HTTP {error.code}.", error.code
                    ) from error
            except (URLError, TimeoutError) as error:
                if attempt == self._max_retries:
                    raise EDINETRequestError(
                        f"EDINET request failed after {attempt + 1} attempts."
                    ) from error
            self._sleeper(min(8.0, 0.5 * (2 ** attempt)))
        raise EDINETRequestError("EDINET request failed.")

    def _wait(self) -> None:
        with self._lock:
            now = self._clock()
            if self._last_request_at is not None:
                remaining = self._minimum_interval - (now - self._last_request_at)
                if remaining > 0:
                    self._sleeper(remaining)
                    now = self._clock()
            self._last_request_at = now


class EDINETStore:
    """EDINET-specific index, code list, date completeness, and downloads."""

    def __init__(self, database_path: Path) -> None:
        self.path = database_path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            connection.executescript("""
            CREATE TABLE IF NOT EXISTS edinet_documents (
              doc_id TEXT PRIMARY KEY, file_date TEXT NOT NULL,
              submit_datetime TEXT NOT NULL, edinet_code TEXT, sec_code TEXT,
              jcn TEXT, filer_name TEXT NOT NULL, doc_type_code TEXT,
              doc_description TEXT, raw_json TEXT NOT NULL, fetched_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_edinet_documents_window
              ON edinet_documents(submit_datetime DESC, doc_id DESC);
            CREATE INDEX IF NOT EXISTS idx_edinet_documents_codes
              ON edinet_documents(edinet_code, sec_code, jcn);
            CREATE TABLE IF NOT EXISTS edinet_file_date_syncs (
              file_date TEXT PRIMARY KEY, status TEXT NOT NULL, fetched_at TEXT NOT NULL,
              record_count INTEGER NOT NULL, error_message TEXT
            );
            CREATE TABLE IF NOT EXISTS edinet_company_codes (
              edinet_code TEXT PRIMARY KEY, filer_name TEXT NOT NULL, sec_code TEXT,
              jcn TEXT, raw_json TEXT NOT NULL, refreshed_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_edinet_company_sec ON edinet_company_codes(sec_code);
            CREATE INDEX IF NOT EXISTS idx_edinet_company_jcn ON edinet_company_codes(jcn);
            CREATE TABLE IF NOT EXISTS edinet_downloads (
              doc_id TEXT NOT NULL, download_type INTEGER NOT NULL, path TEXT NOT NULL,
              size INTEGER NOT NULL, sha256 TEXT NOT NULL, content_type TEXT,
              zip_valid INTEGER, status TEXT NOT NULL, downloaded_at TEXT NOT NULL,
              PRIMARY KEY(doc_id, download_type)
            );
            """)

    def save_date(self, file_date: date, rows: Sequence[Mapping[str, Any]], fetched_at: datetime) -> None:
        with self._connect() as connection:
            for raw in rows:
                preserved_raw = {**dict(raw), "fileDate": file_date.isoformat()}
                disclosure = _parse_disclosure(preserved_raw, file_date)
                connection.execute("""
                INSERT INTO edinet_documents VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(doc_id) DO UPDATE SET file_date=excluded.file_date,
                  submit_datetime=excluded.submit_datetime, edinet_code=excluded.edinet_code,
                  sec_code=excluded.sec_code, jcn=excluded.jcn, filer_name=excluded.filer_name,
                  doc_type_code=excluded.doc_type_code,
                  doc_description=excluded.doc_description, raw_json=excluded.raw_json,
                  fetched_at=excluded.fetched_at
                """, (disclosure.doc_id, file_date.isoformat(),
                       disclosure.submit_datetime.isoformat(), disclosure.edinet_code,
                       disclosure.sec_code, disclosure.jcn, disclosure.filer_name,
                       disclosure.doc_type_code, disclosure.doc_description,
                       json.dumps(preserved_raw, ensure_ascii=False, sort_keys=True),
                       fetched_at.isoformat()))
            connection.execute("""
              INSERT INTO edinet_file_date_syncs VALUES (?, 'success', ?, ?, NULL)
              ON CONFLICT(file_date) DO UPDATE SET status='success',
                fetched_at=excluded.fetched_at, record_count=excluded.record_count,
                error_message=NULL
            """, (file_date.isoformat(), fetched_at.isoformat(), len(rows)))
        LOGGER.info(
            "edinet file_date=%s status=success records=%d fetched_at=%s",
            file_date.isoformat(), len(rows), fetched_at.isoformat(),
        )

    def mark_error(self, file_date: date, fetched_at: datetime, message: str) -> None:
        with self._connect() as connection:
            connection.execute("""
              INSERT INTO edinet_file_date_syncs VALUES (?, 'failure', ?, 0, ?)
              ON CONFLICT(file_date) DO UPDATE SET status='failure',
                fetched_at=excluded.fetched_at, error_message=excluded.error_message
            """, (file_date.isoformat(), fetched_at.isoformat(), message))
        LOGGER.warning(
            "edinet file_date=%s status=failure error=%s",
            file_date.isoformat(), message,
        )

    def date_sync_state(
        self, file_date: date, now: datetime, ttl: timedelta
    ) -> Optional[Mapping[str, Any]]:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT status, fetched_at, error_message FROM edinet_file_date_syncs "
                "WHERE file_date=?",
                (file_date.isoformat(),),
            ).fetchone()
        if not row or now - datetime.fromisoformat(str(row["fetched_at"])) > ttl:
            return None
        return dict(row)

    def rows_for_dates(self, dates: Sequence[date]) -> List[Mapping[str, Any]]:
        if not dates:
            return []
        placeholders = ",".join("?" for _ in dates)
        with self._connect() as connection:
            rows = connection.execute(
                f"SELECT raw_json FROM edinet_documents WHERE file_date IN ({placeholders})",
                tuple(day.isoformat() for day in dates),
            ).fetchall()
        return [json.loads(str(row["raw_json"])) for row in rows]

    def resolve(self, inputs: Sequence[EDINETCompanyInput]) -> Tuple[Tuple[ResolvedCompany, ...], Tuple[UnresolvedCompany, ...]]:
        resolved, unresolved = [], []
        with self._connect() as connection:
            for company in inputs:
                clauses, values = [], []
                for column, value in (("edinet_code", company.edinet_code),
                                      ("sec_code", _normalize_sec(company.sec_code)),
                                      ("jcn", company.jcn)):
                    if value:
                        clauses.append(f"{column} = ?")
                        values.append(value.strip().upper())
                if company.name:
                    clauses.append("filer_name = ? COLLATE NOCASE")
                    values.append(company.name.strip())
                rows = connection.execute(
                    "SELECT * FROM edinet_company_codes WHERE " + " AND ".join(clauses), values
                ).fetchall() if clauses else []
                if len(rows) == 1:
                    row = rows[0]
                    resolved.append(ResolvedCompany(str(row["edinet_code"]),
                        str(row["filer_name"]), row["sec_code"], row["jcn"]))
                else:
                    unresolved.append(UnresolvedCompany(asdict(company),
                        "not_found" if not rows else "ambiguous",
                        tuple(str(row["edinet_code"]) for row in rows)))
        return tuple(resolved), tuple(unresolved)

    def replace_codes(self, rows: Sequence[Mapping[str, str]], refreshed_at: datetime) -> int:
        with self._connect() as connection:
            connection.execute("DELETE FROM edinet_company_codes")
            for row in rows:
                code = _pick(row, "ＥＤＩＮＥＴコード", "EDINET Code", "edinetCode")
                name = _pick(row, "提出者名", "Filer Name", "filerName")
                if not code or not name:
                    continue
                sec = _normalize_sec(_pick(row, "証券コード", "Securities Code", "secCode"))
                jcn = _pick(row, "提出者法人番号", "法人番号", "JCN") or None
                connection.execute("INSERT INTO edinet_company_codes VALUES (?,?,?,?,?,?)",
                    (code.upper(), name, sec, jcn,
                     json.dumps(dict(row), ensure_ascii=False, sort_keys=True),
                     refreshed_at.isoformat()))
            return int(connection.execute("SELECT COUNT(*) n FROM edinet_company_codes").fetchone()["n"])

    def record_download(self, result: DownloadResult, content_type: str, downloaded_at: datetime) -> None:
        with self._connect() as connection:
            connection.execute("""INSERT OR REPLACE INTO edinet_downloads
              VALUES (?,?,?,?,?,?,?,?,?)""", (result.doc_id, result.download_type,
              str(result.path), result.size, result.sha256, content_type,
              None if result.zip_valid is None else int(result.zip_valid),
              result.status, downloaded_at.isoformat()))

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(str(self.path))
        connection.row_factory = sqlite3.Row
        try:
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()


class EDINETConnector:
    """Indexed-first official EDINET service and shared pipeline connector."""

    name = "edinet"
    provider = "EDINET"
    source_wide_collection = True
    max_lookback_days = 3650
    secret_fields = (SecretField(env="EDINET_API_KEY", label="EDINET API Key",
        help="Official EDINET API v2 subscription key."),)

    def __init__(self, client: EDINETClient, store: EDINETStore, *,
                 cache_ttl: timedelta = timedelta(seconds=60),
                 download_root: Path = Path("data/downloads"),
                 now: Callable[[], datetime] = lambda: datetime.now(timezone.utc)) -> None:
        self.client, self.store = client, store
        self.cache_ttl, self.download_root, self._now = cache_ttl, download_root, now

    @classmethod
    def from_environment(cls) -> "EDINETConnector":
        if cls.configuration_error():
            raise ConnectorUnavailableError(cls.configuration_error() or "EDINET unavailable")
        return cls(EDINETClient.from_environment(), EDINETStore(Path(
            os.environ.get("EDINET_DATABASE_PATH", "data/investment_monitor.sqlite3"))),
            cache_ttl=timedelta(seconds=_env_float("EDINET_CACHE_TTL_SECONDS", 60)),
            download_root=Path(os.environ.get("EDINET_DOWNLOAD_ROOT", "data/downloads")))

    @classmethod
    def configuration_error(cls) -> Optional[str]:
        return None if os.environ.get("EDINET_API_KEY", "").strip() else "EDINET_API_KEY is not configured."

    def get_watchlist_disclosures_since(self, *, companies: Sequence[Any],
            since: Optional[datetime] = None, now: Optional[datetime] = None,
            doc_type_codes: Optional[Sequence[str]] = None,
            include_withdrawn: bool = False, include_downloads: bool = False,
            download_types: Sequence[int] = (1, 2)) -> WatchlistDisclosureResult:
        end = _aware(now or self._now())
        start = _aware(since or (end - timedelta(hours=24)))
        if start > end:
            raise ValueError("since must not be after now")
        inputs = tuple(_company_input(value) for value in companies)
        resolvable_inputs = tuple(company for company in inputs if not company.edinet_code)
        resolved, unresolved = self.store.resolve(resolvable_inputs)
        # Explicit EDINET codes do not require a code-list row.
        explicit = [ResolvedCompany(c.edinet_code.upper(), c.name or c.edinet_code,
                    _normalize_sec(c.sec_code), c.jcn) for c in inputs if c.edinet_code]
        by_code = {company.edinet_code: company for company in (*resolved, *explicit)}
        dates = _japan_dates(start, end)
        errors, fetched_at = [], self._now().astimezone(timezone.utc)
        for day in dates:
            state = self.store.date_sync_state(day, fetched_at, self.cache_ttl)
            if state and state["status"] == "success":
                LOGGER.debug("edinet file_date=%s cache=hit", day.isoformat())
                continue
            if state and state["status"] == "failure":
                LOGGER.debug("edinet file_date=%s negative_cache=hit", day.isoformat())
                errors.append(EDINETDateError(
                    day, str(state["error_message"] or "recent EDINET request failed"), True
                ))
                continue
            try:
                rows = _results(self.client.list_documents(day))
                self.store.save_date(day, rows, fetched_at)
            except EDINETError as error:
                self.store.mark_error(day, fetched_at, str(error))
                errors.append(EDINETDateError(day, str(error),
                    not isinstance(error, EDINETRequestError) or error.status_code in RETRYABLE_STATUS_CODES))
        allowed_types = set(doc_type_codes or ())
        items = []
        for raw in self.store.rows_for_dates(dates):
            disclosure = _parse_disclosure(raw, date.fromisoformat(str(raw.get("fileDate") or raw.get("submitDateTime", "")[:10])))
            if not (start <= disclosure.submit_datetime <= end):
                continue
            matched_codes = tuple(dict.fromkeys(
                str(raw.get(field_name) or "").upper()
                for _, field_name in ROLE_FIELDS
                if str(raw.get(field_name) or "").upper() in by_code
            ))
            roles = tuple(role for role, field_name in ROLE_FIELDS
                          if str(raw.get(field_name) or "").upper() in matched_codes)
            matched_sec_codes = tuple(dict.fromkeys(
                code for code in (
                    by_code[edinet_code].sec_code for edinet_code in matched_codes
                ) if code
            ))
            if not roles:
                # secCode/JCN fallback for filer when code list is not ready.
                matching_sec = tuple(dict.fromkeys(
                    _normalize_sec(c.sec_code) for c in inputs
                    if c.sec_code and _normalize_sec(disclosure.sec_code) == _normalize_sec(c.sec_code)
                ))
                if matching_sec:
                    roles, matched_sec_codes = ("filer",), matching_sec
                elif any(disclosure.jcn == c.jcn and c.jcn for c in inputs):
                    roles = ("filer",)
            if not roles or (allowed_types and disclosure.doc_type_code not in allowed_types):
                continue
            if not include_withdrawn and _is_withdrawn(disclosure.withdrawal_status):
                continue
            disclosure = EDINETDisclosure(**{
                **disclosure.__dict__,
                "match_roles": roles,
                "matched_edinet_codes": matched_codes,
                "matched_sec_codes": matched_sec_codes,
            })
            items.append(disclosure)
        items.sort(key=lambda item: (item.submit_datetime, item.doc_id), reverse=True)
        if include_downloads and items:
            with ThreadPoolExecutor(max_workers=min(4, len(items))) as executor:
                futures = [executor.submit(
                    self.download_document, item.doc_id, download_types,
                    file_date=item.file_date,
                ) for item in items]
                for future in futures:
                    future.result()
        by_company: Dict[str, int] = {}
        by_type: Dict[str, int] = {}
        for item in items:
            company_keys = item.matched_edinet_codes or item.matched_sec_codes or (
                item.edinet_code or item.sec_code or item.jcn or item.filer_name,
            )
            for key in company_keys:
                by_company[key] = by_company.get(key, 0) + 1
            dtype = item.doc_type_code or "unknown"
            by_type[dtype] = by_type.get(dtype, 0) + 1
        return WatchlistDisclosureResult(tuple(items), unresolved, tuple(errors),
            bool(errors), start, end, fetched_at, by_company, by_type)

    # Product/API spelling alias.
    getWatchlistDisclosuresSince = get_watchlist_disclosures_since

    def list_documents(self, start_date: date, end_date: Optional[date] = None) -> Tuple[EDINETDisclosure, ...]:
        end = end_date or start_date
        self.sync_range(start_date, end)
        return tuple(_parse_disclosure(raw, date.fromisoformat(str(raw.get("fileDate") or raw["submitDateTime"][:10])))
                     for raw in self.store.rows_for_dates(tuple(_date_range(start_date, end))))

    def get_document(self, doc_id: str) -> Optional[EDINETDisclosure]:
        with self.store._connect() as connection:
            row = connection.execute("SELECT file_date, raw_json FROM edinet_documents WHERE doc_id=?", (doc_id,)).fetchone()
        return _parse_disclosure(json.loads(row["raw_json"]), date.fromisoformat(row["file_date"])) if row else None

    def sync_range(self, start_date: date, end_date: date) -> Mapping[str, Any]:
        if start_date > end_date or end_date > self._now().astimezone(JAPAN_TIME).date():
            raise ValueError("EDINET sync dates must be ordered and not in the future")
        successes, errors = [], []
        for day in _date_range(start_date, end_date):
            fetched = self._now().astimezone(timezone.utc)
            try:
                rows = _results(self.client.list_documents(day))
                self.store.save_date(day, rows, fetched)
                successes.append((day.isoformat(), len(rows)))
            except EDINETError as error:
                self.store.mark_error(day, fetched, str(error)); errors.append((day.isoformat(), str(error)))
        return {"dates": successes, "errors": errors, "partial": bool(errors)}

    syncRange = sync_range

    def sync_incremental(self, overlap_days: int = 1) -> Mapping[str, Any]:
        today = self._now().astimezone(JAPAN_TIME).date()
        with self.store._connect() as connection:
            row = connection.execute("SELECT MAX(file_date) latest FROM edinet_file_date_syncs WHERE status='success'").fetchone()
        start = date.fromisoformat(row["latest"]) - timedelta(days=overlap_days) if row and row["latest"] else today - timedelta(days=1)
        return self.sync_range(start, today)

    syncIncremental = sync_incremental

    def refresh_code_list(self) -> int:
        body = _download_public_official_file(OFFICIAL_CODE_LIST_URL)
        if not zipfile.is_zipfile(BytesIO(body)):
            raise EDINETDataError("Official EDINET code list is not a valid ZIP.")
        with zipfile.ZipFile(BytesIO(body)) as archive:
            csv_names = [name for name in archive.namelist() if name.lower().endswith(".csv")]
            if len(csv_names) != 1:
                raise EDINETDataError("Official EDINET code-list ZIP must contain one CSV.")
            with archive.open(csv_names[0]) as binary:
                text = TextIOWrapper(binary, encoding="cp932", errors="strict", newline="")
                reader = csv.reader(text)
                header = None
                data_rows = []
                for row in reader:
                    if header is None:
                        if row and row[0].strip() == "ＥＤＩＮＥＴコード":
                            header = row
                        continue
                    data_rows.append(row)
                if header is None:
                    raise EDINETDataError("Official EDINET code list header was not found.")
                rows = [dict(zip(header, row)) for row in data_rows]
        return self.store.replace_codes(rows, self._now().astimezone(timezone.utc))

    refreshCodeList = refresh_code_list

    def resolve_companies(self, inputs: Sequence[Any]) -> Mapping[str, Any]:
        resolved, unresolved = self.store.resolve(tuple(_company_input(value) for value in inputs))
        return {"resolved": resolved, "unresolved": unresolved}

    resolveCompanies = resolve_companies

    def download_document(self, doc_id: str, types: Sequence[int] = (1, 2), *,
                          file_date: Optional[date] = None) -> Tuple[DownloadResult, ...]:
        document = self.get_document(doc_id)
        day = file_date or (document.file_date if document else None)
        if day is None:
            raise ValueError("file_date is required for an unindexed document")
        def download_one(download_type: int) -> DownloadResult:
            body, content_type = self.client.download_document(doc_id, int(download_type))
            extension = ".pdf" if int(download_type) == 2 else ".zip"
            destination = self.download_root / "edinet" / day.isoformat() / doc_id / f"type-{download_type}" / ("document" + extension)
            destination.parent.mkdir(parents=True, exist_ok=True)
            digest = sha256(body).hexdigest()
            zip_valid = None if extension == ".pdf" else zipfile.is_zipfile(BytesIO(body))
            status = "stored" if len(body) >= 16 and zip_valid is not False else "skipped"
            if status == "stored":
                temporary = destination.with_suffix(destination.suffix + ".tmp")
                temporary.write_bytes(body); temporary.replace(destination)
            result = DownloadResult(doc_id, int(download_type), destination, len(body), digest, zip_valid, status)
            self.store.record_download(result, content_type, self._now().astimezone(timezone.utc))
            return result
        normalized_types = tuple(dict.fromkeys(int(value) for value in types))
        with ThreadPoolExecutor(max_workers=min(4, len(normalized_types) or 1)) as executor:
            results = list(executor.map(download_one, normalized_types))
        return tuple(sorted(results, key=lambda result: result.download_type))

    downloadDocument = download_document

    def collect(self, request: CollectionRequest) -> List[InformationItem]:
        result = self.get_watchlist_disclosures_since(
            companies=tuple(EDINETCompanyInput(sec_code=ticker) for ticker in request.tickers
                            if request.market_for(ticker) == MARKET_JP),
            since=datetime.combine(request.start_date, datetime.min.time(), JAPAN_TIME),
            now=datetime.combine(request.end_date + timedelta(days=1), datetime.min.time(), JAPAN_TIME) - timedelta(microseconds=1),
        )
        return [_to_information_item(item, result.fetched_at) for item in result.items]


def _parse_disclosure(raw: Mapping[str, Any], file_date: date) -> EDINETDisclosure:
    doc_id = str(raw.get("docID") or "").strip()
    submitted = str(raw.get("submitDateTime") or "").strip()
    if not doc_id or not submitted:
        raise EDINETDataError("EDINET record is missing docID or submitDateTime.")
    timestamp = datetime.fromisoformat(submitted.replace("Z", "+00:00"))
    if timestamp.tzinfo is None:
        timestamp = timestamp.replace(tzinfo=JAPAN_TIME)
    return EDINETDisclosure(doc_id, timestamp, file_date,
        str(raw.get("filerName") or raw.get("edinetCode") or "Unavailable"),
        _optional(raw, "edinetCode"), _normalize_sec(_optional(raw, "secCode")),
        _optional(raw, "JCN"), _optional(raw, "docTypeCode"),
        _optional(raw, "docDescription"), period_start=_optional_date(raw, "periodStart"),
        period_end=_optional_date(raw, "periodEnd"),
        issuer_edinet_code=_optional(raw, "issuerEdinetCode"),
        subject_edinet_code=_optional(raw, "subjectEdinetCode"),
        subsidiary_edinet_code=_optional(raw, "subsidiaryEdinetCode"),
        parent_doc_id=_optional(raw, "parentDocID"),
        withdrawal_status=_optional(raw, "withdrawalStatus"),
        disclosure_status=_optional(raw, "disclosureStatus"),
        doc_info_edit_status=_optional(raw, "docInfoEditStatus"),
        flags={key: _optional(raw, key) for key in
               ("xbrlFlag", "pdfFlag", "attachDocFlag", "englishDocFlag", "csvFlag", "legalStatus")},
        raw=dict(raw))


def _to_information_item(item: EDINETDisclosure, collected_at: datetime) -> InformationItem:
    related = tuple(dict.fromkeys(code for code in (
        item.edinet_code, item.issuer_edinet_code, item.subject_edinet_code,
        item.subsidiary_edinet_code, _normalize_sec(item.sec_code),
        *item.matched_edinet_codes, *item.matched_sec_codes,
    ) if code))
    raw = {**dict(item.raw), "official_source_url": item.official_url,
           "fileDate": item.file_date.isoformat(), "matchRoles": list(item.match_roles),
           "matchedEdinetCodes": list(item.matched_edinet_codes),
           "matchedSecCodes": list(item.matched_sec_codes)}
    return InformationItem(source="edinet", source_type="regulatory_disclosure",
        external_id=item.doc_id, tickers=related or (item.edinet_code or item.doc_id,),
        issuer=item.filer_name, published_at=item.submit_datetime,
        title=item.doc_description or item.doc_type_code or "EDINET disclosure",
        document_type=item.doc_type_code or "unknown", url=item.official_url,
        collected_at=collected_at, raw_metadata=raw, market=MARKET_JP,
        effective_at=item.submit_datetime)


def _results(payload: Mapping[str, Any]) -> List[Mapping[str, Any]]:
    results = payload.get("results")
    if not isinstance(results, list) or any(not isinstance(row, dict) for row in results):
        raise EDINETDataError("EDINET documents response has invalid results.")
    return [dict(row) for row in results]


def _company_input(value: Any) -> EDINETCompanyInput:
    if isinstance(value, EDINETCompanyInput): return value
    if isinstance(value, Mapping):
        return EDINETCompanyInput(value.get("edinetCode") or value.get("edinet_code"),
            value.get("secCode") or value.get("sec_code"), value.get("JCN") or value.get("jcn"), value.get("name"))
    text = str(value).strip()
    if text.upper().startswith("E") and text[1:].isdigit(): return EDINETCompanyInput(edinet_code=text.upper())
    if text.isdigit() and len(text) in {4, 5}: return EDINETCompanyInput(sec_code=text)
    if text.isdigit() and len(text) == 13: return EDINETCompanyInput(jcn=text)
    return EDINETCompanyInput(name=text)


def _normalize_sec(value: Optional[str]) -> Optional[str]:
    text = str(value or "").strip().upper()
    if len(text) == 5 and text.endswith("0"): text = text[:4]
    return text or None


def _japan_dates(start: datetime, end: datetime) -> Tuple[date, ...]:
    return tuple(_date_range(start.astimezone(JAPAN_TIME).date(), end.astimezone(JAPAN_TIME).date()))


def _date_range(start: date, end: date) -> Iterable[date]:
    current = start
    while current <= end:
        yield current; current += timedelta(days=1)


def _aware(value: datetime) -> datetime:
    if value.tzinfo is None: raise ValueError("timestamps must be timezone-aware")
    return value.astimezone(timezone.utc)


def _optional(raw: Mapping[str, Any], key: str) -> Optional[str]:
    value = raw.get(key)
    return None if value is None or str(value).strip() == "" else str(value).strip()


def _optional_date(raw: Mapping[str, Any], key: str) -> Optional[date]:
    value = _optional(raw, key)
    return date.fromisoformat(value) if value else None


def _is_withdrawn(value: Optional[str]) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "withdrawn"}


def _pick(row: Mapping[str, str], *keys: str) -> str:
    for key in keys:
        if str(row.get(key) or "").strip(): return str(row[key]).strip()
    return ""


def _env_float(name: str, default: float) -> float:
    try: return float(os.environ.get(name, str(default)))
    except ValueError as error: raise ValueError(f"{name} must be numeric") from error


def _env_int(name: str, default: int) -> int:
    try: return int(os.environ.get(name, str(default)))
    except ValueError as error: raise ValueError(f"{name} must be an integer") from error


def _download_public_official_file(
    url: str,
    *,
    opener: Callable[..., Any] = urlopen,
    timeout: float = 30.0,
) -> bytes:
    """Download a public EDINET asset without ever attaching the API key."""
    if urlsplit(url).netloc != "disclosure2dl.edinet-fsa.go.jp":
        raise ValueError("Unsupported EDINET public download host")
    request = Request(url, headers={"User-Agent": "InvestmentMonitor/0.1 EDINET connector"})
    try:
        with opener(request, timeout=timeout) as response:
            return bytes(response.read())
    except (HTTPError, URLError, TimeoutError) as error:
        raise EDINETRequestError("Official EDINET public-file download failed.") from error