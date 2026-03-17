CREATE TABLE IF NOT EXISTS scoring_rounds (
    id SERIAL PRIMARY KEY,
    round_number INTEGER NOT NULL UNIQUE,
    status TEXT NOT NULL DEFAULT 'pending',
    snapshot_hash TEXT,
    scores_hash TEXT,
    vl_sequence INTEGER,
    ipfs_cid TEXT,
    memo_tx_hash TEXT,
    error_message TEXT,
    started_at TIMESTAMPTZ,
    completed_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_scoring_rounds_status ON scoring_rounds(status);
