CREATE TABLE IF NOT EXISTS system_lists (
    id INTEGER PRIMARY KEY,
    slug TEXT NOT NULL UNIQUE,
    name TEXT NOT NULL UNIQUE,
    position INTEGER NOT NULL UNIQUE,
    is_fixed INTEGER NOT NULL DEFAULT 1 CHECK (is_fixed IN (0, 1))
);

CREATE TABLE IF NOT EXISTS companies (
    id INTEGER PRIMARY KEY,
    ticker TEXT NOT NULL UNIQUE,
    name TEXT NOT NULL,
    exchange TEXT,
    cik TEXT,
    mapping_status TEXT NOT NULL DEFAULT 'mapped',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS company_list_memberships (
    company_id INTEGER NOT NULL,
    list_id INTEGER NOT NULL,
    created_at TEXT NOT NULL,
    PRIMARY KEY (company_id, list_id),
    FOREIGN KEY (company_id) REFERENCES companies(id) ON DELETE RESTRICT,
    FOREIGN KEY (list_id) REFERENCES system_lists(id) ON DELETE RESTRICT
);

CREATE TABLE IF NOT EXISTS information_read_state (
    item_id INTEGER PRIMARY KEY,
    is_read INTEGER NOT NULL DEFAULT 0 CHECK (is_read IN (0, 1)),
    updated_at TEXT NOT NULL,
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

CREATE TABLE IF NOT EXISTS app_settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

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
