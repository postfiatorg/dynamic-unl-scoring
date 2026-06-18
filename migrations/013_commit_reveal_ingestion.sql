-- Foundation-side ingestion of validator commit/reveal memos for M2.6
-- convergence monitoring. Submissions are stored at per-transaction grain
-- (one row per on-chain memo, unique on tx_hash) so conflicting duplicate
-- commits/reveals from the same validator are preserved for the downstream
-- first-valid-by-ledger-order selection in M2.6.2. round_number is the
-- on-chain identifier carried in the memo and is what later steps join to
-- scoring_rounds.

CREATE TABLE IF NOT EXISTS validator_commits (
    tx_hash              TEXT PRIMARY KEY,
    round_number         INTEGER NOT NULL,
    validator_master_key TEXT,
    input_package_hash   TEXT,
    commitment_hash      TEXT,
    protocol_version     INTEGER,
    network              TEXT,
    signature            TEXT,
    sender_account       TEXT,
    ledger_index         BIGINT NOT NULL,
    transaction_index    INTEGER NOT NULL,
    ledger_close_time    TIMESTAMPTZ,
    payload              JSONB NOT NULL,
    ingested_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_validator_commits_round_validator
    ON validator_commits (round_number, validator_master_key);

CREATE INDEX IF NOT EXISTS idx_validator_commits_ledger_order
    ON validator_commits (round_number, ledger_index, transaction_index);

CREATE TABLE IF NOT EXISTS validator_reveals (
    tx_hash              TEXT PRIMARY KEY,
    round_number         INTEGER NOT NULL,
    validator_master_key TEXT,
    input_package_hash   TEXT,
    model_response_hash  TEXT,
    validator_scores_hash TEXT,
    selected_unl_hash    TEXT,
    salt                 TEXT,
    protocol_version     INTEGER,
    network              TEXT,
    signature            TEXT,
    sender_account       TEXT,
    ledger_index         BIGINT NOT NULL,
    transaction_index    INTEGER NOT NULL,
    ledger_close_time    TIMESTAMPTZ,
    payload              JSONB NOT NULL,
    ingested_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_validator_reveals_round_validator
    ON validator_reveals (round_number, validator_master_key);

CREATE INDEX IF NOT EXISTS idx_validator_reveals_ledger_order
    ON validator_reveals (round_number, ledger_index, transaction_index);

-- Forward cursor for the chain watcher: the highest ledger index already
-- scanned for an account. The next pass resumes from here; overlap is safe
-- because submission inserts are idempotent on tx_hash.
CREATE TABLE IF NOT EXISTS convergence_ingestion_cursor (
    account           TEXT PRIMARY KEY,
    last_ledger_index BIGINT NOT NULL,
    updated_at        TIMESTAMPTZ NOT NULL DEFAULT now()
);
