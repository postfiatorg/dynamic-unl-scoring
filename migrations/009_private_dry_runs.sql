CREATE TABLE IF NOT EXISTS dry_runs (
    id SERIAL PRIMARY KEY,
    status TEXT NOT NULL DEFAULT 'COLLECTING',
    snapshot_hash TEXT,
    scores_hash TEXT,
    error_message TEXT,
    started_at TIMESTAMPTZ,
    completed_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_dry_runs_status ON dry_runs(status);
CREATE INDEX IF NOT EXISTS idx_dry_runs_created_at ON dry_runs(created_at);

CREATE TABLE IF NOT EXISTS dry_run_raw_evidence (
    dry_run_id INTEGER NOT NULL REFERENCES dry_runs(id) ON DELETE CASCADE,
    source TEXT NOT NULL,
    raw_data JSONB NOT NULL,
    content_hash TEXT NOT NULL,
    publishable BOOLEAN NOT NULL DEFAULT TRUE,
    captured_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (dry_run_id, source)
);

CREATE INDEX IF NOT EXISTS idx_dry_run_raw_evidence_source
    ON dry_run_raw_evidence(source);

CREATE TABLE IF NOT EXISTS dry_run_artifacts (
    dry_run_id INTEGER NOT NULL REFERENCES dry_runs(id) ON DELETE CASCADE,
    file_path TEXT NOT NULL,
    content JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (dry_run_id, file_path)
);
