-- Sealed convergence reports for M2.6 convergence monitoring: one finalized,
-- content-addressed report per round, anchored on-chain. A row existing means
-- the round is sealed (seal-once is enforced by the round_number primary key);
-- the watcher stops re-verifying a sealed round. The full report is kept in
-- JSONB for the HTTPS retrieval fallback, mirroring the audit-bundle pattern.
CREATE TABLE IF NOT EXISTS convergence_reports (
    round_number           INTEGER PRIMARY KEY,
    convergence_bundle_cid TEXT NOT NULL,
    anchor_tx_hash         TEXT,
    report                 JSONB NOT NULL,
    sealed_at              TIMESTAMPTZ NOT NULL DEFAULT now()
);
