CREATE TABLE IF NOT EXISTS raw_evidence (
    id SERIAL PRIMARY KEY,
    round_number INTEGER NOT NULL,
    source TEXT NOT NULL,
    raw_data JSONB NOT NULL,
    content_hash TEXT NOT NULL,
    publishable BOOLEAN NOT NULL DEFAULT TRUE,
    captured_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_raw_evidence_round_number ON raw_evidence(round_number);
CREATE INDEX idx_raw_evidence_source ON raw_evidence(source);
