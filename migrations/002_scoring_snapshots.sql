CREATE TABLE IF NOT EXISTS scoring_snapshots (
    id SERIAL PRIMARY KEY,
    round_id INTEGER NOT NULL REFERENCES scoring_rounds(id),
    content_hash TEXT NOT NULL,
    snapshot_data JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_scoring_snapshots_round_id ON scoring_snapshots(round_id);
CREATE INDEX idx_scoring_snapshots_content_hash ON scoring_snapshots(content_hash);
