CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY,
    subject TEXT NOT NULL UNIQUE,
    display_name TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('legacy', 'active', 'disabled')),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS system_lists (
    id INTEGER PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
    slug TEXT NOT NULL,
    name TEXT NOT NULL,
    name_key TEXT NOT NULL,
    position INTEGER NOT NULL,
    is_fixed INTEGER NOT NULL DEFAULT 1 CHECK (is_fixed IN (0, 1))
    ,UNIQUE (user_id, id)
    ,UNIQUE (user_id, slug)
    ,UNIQUE (user_id, name_key)
    ,UNIQUE (user_id, position)
);

CREATE TABLE IF NOT EXISTS companies (
    id INTEGER PRIMARY KEY,
    ticker TEXT NOT NULL,
    market TEXT NOT NULL DEFAULT 'us',
    name TEXT NOT NULL,
    exchange TEXT,
    cik TEXT,
    mapping_status TEXT NOT NULL DEFAULT 'mapped',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE (ticker, market)
);

CREATE TABLE IF NOT EXISTS company_list_memberships (
    user_id INTEGER NOT NULL,
    company_id INTEGER NOT NULL,
    list_id INTEGER NOT NULL,
    created_at TEXT NOT NULL,
    PRIMARY KEY (user_id, company_id, list_id),
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE RESTRICT,
    FOREIGN KEY (company_id) REFERENCES companies(id) ON DELETE RESTRICT,
    FOREIGN KEY (list_id) REFERENCES system_lists(id) ON DELETE RESTRICT,
    FOREIGN KEY (user_id, list_id) REFERENCES system_lists(user_id, id) ON DELETE RESTRICT
);

CREATE TABLE IF NOT EXISTS information_read_state (
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    item_id INTEGER NOT NULL,
    is_read INTEGER NOT NULL DEFAULT 0 CHECK (is_read IN (0, 1)),
    updated_at TEXT NOT NULL,
    PRIMARY KEY (user_id, item_id),
    FOREIGN KEY (item_id) REFERENCES information_items(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS ingestion_runs (
    id INTEGER PRIMARY KEY,
    source TEXT NOT NULL,
    started_at TEXT NOT NULL,
    finished_at TEXT,
    status TEXT NOT NULL,
    companies_processed INTEGER,
    successful_companies INTEGER,
    failed_companies INTEGER,
    records_fetched INTEGER,
    records_inserted INTEGER,
    duplicate_records INTEGER,
    error_summary TEXT
);

CREATE TABLE IF NOT EXISTS ingestion_logs (
    id INTEGER PRIMARY KEY,
    run_id INTEGER,
    occurred_at TEXT NOT NULL,
    operation TEXT NOT NULL,
    source TEXT NOT NULL,
    ticker TEXT,
    status TEXT NOT NULL,
    records_read INTEGER,
    records_written INTEGER,
    error_message TEXT,
    FOREIGN KEY (run_id) REFERENCES ingestion_runs(id) ON DELETE SET NULL
);

CREATE TABLE IF NOT EXISTS source_ticker_sync_state (
    source TEXT NOT NULL,
    ticker TEXT NOT NULL,
    market TEXT NOT NULL,
    initial_status TEXT NOT NULL DEFAULT 'pending'
        CHECK (initial_status IN ('pending', 'complete', 'partial', 'failure')),
    last_status TEXT,
    coverage_kind TEXT NOT NULL DEFAULT 'unknown'
        CHECK (coverage_kind IN (
            'complete_window', 'bounded_window', 'feed_snapshot', 'unknown'
        )),
    requested_start_date TEXT,
    requested_end_date TEXT,
    effective_start_date TEXT,
    effective_end_date TEXT,
    last_attempt_at TEXT,
    last_success_at TEXT,
    last_error TEXT,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (source, ticker, market)
);

CREATE TABLE IF NOT EXISTS app_settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

-- These compatibility indexes must remain valid when this idempotent base
-- script runs against the pre-multi-user schema. Owner-leading indexes are
-- created by the versioned foundation migration after its table rebuild.
CREATE INDEX IF NOT EXISTS idx_memberships_list_company
ON company_list_memberships(list_id, company_id);

CREATE INDEX IF NOT EXISTS idx_companies_ticker_name
ON companies(ticker, name);

CREATE INDEX IF NOT EXISTS idx_read_state_read_item
ON information_read_state(is_read, item_id);

CREATE INDEX IF NOT EXISTS idx_ingestion_runs_source_started
ON ingestion_runs(source, started_at DESC);

CREATE INDEX IF NOT EXISTS idx_ingestion_logs_filters
ON ingestion_logs(source, status, occurred_at DESC);

CREATE INDEX IF NOT EXISTS idx_source_ticker_sync_state_status
ON source_ticker_sync_state(initial_status, source, market);
